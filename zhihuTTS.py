import io
import logging
import os
import re
import subprocess
import threading
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from google import genai
from google.genai import types

PARTS_DIR = Path(__file__).parent / "Videos" / "parts"
MARKDOWNS_DIR = Path(__file__).parent / "Markdowns"
PROGRESS_FILE = Path(__file__).parent / ".progress.json"
LOG_FILE = Path(__file__).parent / "zhihuTTS.log"

MAX_RETRIES = 6
RETRY_DELAY = 65      # seconds，覆盖免费层 ~58s 限流窗口
PART_INTERVAL = 65    # 片段间强制等待，避免触发每分钟 token 限额
UPLOAD_WORKERS = 2    # 并发上传数，保护代理带宽

# 上传模式：
#   files_api  — 默认，通过 Google Files API 上传
#   base64     — 将视频文件 base64 编码后内联传入（适合小文件，大文件会超出请求体限制）
# 注意：不要使用 file_uri 模式，Gemini 只能解析 YouTube URL，GitHub/CDN 等通用 URL 无法解析。
UPLOAD_MODE = os.environ.get("UPLOAD_MODE", "files_api")

PROMPT_TEXT = """
# 角色与目标
你是一个顶级的知识库数据提取专家。我将上传同一个完整视频被切分成的若干连续片段（part000、part001……），请将它们视为一个完整视频，按时间顺序提取内容，转化为一份**高度详尽、结构化、完全适合导入 NotebookLM 作为底层语料的 Markdown 文档**。

# 提取原则（至关重要）
1. **拒绝极简摘要：** 我需要的是"重型知识沉淀"，请尽可能详尽地提取视频中的具体细节、核心论点、数据支撑和案例，而不是只给我大纲。
2. **提取视觉信息：** 如果视频中出现了幻灯片（PPT）、代码屏幕、架构图或白板板书，请务必用文字把屏幕上的核心内容"转录"下来，并附上描述。
3. **保留专业术语：** 精准提取视频中的专有名词、工具名称、人名和核心概念，不要做通俗化处理，确保后续检索的准确性。
4. **时间线锚点：** 请按照视频的逻辑章节或时间块进行切分，并在每个段落前标注大致的时间戳（如 [00:15:20]）。

# 必须输出的 Markdown 结构

请严格按照以下模板输出内容：

## 1. 视频元数据
- **推测主题：** （用一句话概括视频核心内容）
- **核心关键词：** （提供 5-10 个便于检索的关键词/标签）
- **适用受众/场景：** （这段视频主要解决什么问题）

## 2. 核心知识字典（Glossary）
（提取视频中反复出现的 3-5 个核心概念或专业术语，并给出视频中的定义，帮助 LLM 统一概念）

## 3. 详尽内容解析（按时间线或章节）
（请根据视频长度，拆分为多个逻辑章节。针对每个章节，请提供：）
### [开始时间 - 结束时间] 章节标题
- **核心论点：** （本段的重点结论）
- **详细展开：** （详尽记录演讲者的具体解释、举例和论证过程）
- **视觉/屏幕内容：** （如果屏幕上有图表、文字、代码或演示操作，请详细描述。如果是代码或配置，请使用代码块 ``` 包裹）
- **重要金句/原话：** （提取 1-2 句演讲者的关键原话，加上引号）

## 4. 遗留问题与下一步行动（如有）
（视频结尾提到的待办事项、推荐的拓展资源，或未解决的问题）

# 执行要求
由于视频长达 2-3 小时，信息量极大。请保持极高的专注度，不要省略中间章节。如果你的输出达到了字数上限，请停在当前完整的段落，我会回复"继续"，你再接着上文输出。
"""

_logger = logging.getLogger("zhihuTTS")


def _setup_logging():
    _logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(fh)


def _parse_retry_delay(error: Exception) -> int:
    """从 429 错误信息中提取建议等待秒数，找不到则返回 RETRY_DELAY。"""
    match = re.search(r'retry in (\d+(?:\.\d+)?)s', str(error), re.IGNORECASE)
    return int(float(match.group(1))) + 10 if match else RETRY_DELAY


_print_lock = threading.Lock()
_progress_lock = threading.Lock()


def tprint(msg: str, level: str = "info"):
    with _print_lock:
        print(msg, flush=True)
    getattr(_logger, level)(msg)


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress: dict):
    with _progress_lock:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)


def group_parts(parts_dir: Path) -> dict[str, list[Path]]:
    """将 parts 目录下的文件按视频名分组，返回 {视频名: [part000, part001, ...]}。"""
    groups: dict[str, list[Path]] = {}
    for p in parts_dir.glob("*_part*.mp4"):
        stem = re.sub(r"_part\d+$", "", p.stem)
        groups.setdefault(stem, []).append(p)
    for parts in groups.values():
        parts.sort(key=lambda p: int(m.group(1)) if (m := re.search(r'part(\d+)', p.stem, re.IGNORECASE)) else 0)
    return dict(sorted(groups.items()))


class _ProgressFile(io.RawIOBase):
    """继承 RawIOBase，每 5% 打印一行带标签的进度。"""
    def __init__(self, path: Path, label: str):
        super().__init__()
        self._f = open(path, "rb")
        self._size = path.stat().st_size
        self._uploaded = 0
        self._start = time.time()
        self._label = label
        self._last_pct = -5

    def readinto(self, b):
        data = self._f.read(len(b))
        n = len(data)
        if n:
            b[:n] = data
        self._uploaded += n
        pct = self._uploaded / self._size * 100 if self._size else 0
        if pct - self._last_pct >= 5 or (n == 0 and self._uploaded > 0):
            elapsed = time.time() - self._start
            speed = self._uploaded / elapsed / 1024 / 1024 if elapsed > 0 else 0
            done_mb = self._uploaded / 1024 / 1024
            total_mb = self._size / 1024 / 1024
            tprint(f"  [{self._label}] 上传: {pct:5.1f}%  {done_mb:.0f}/{total_mb:.0f} MB  {speed:.2f} MB/s")
            self._last_pct = pct
        return n

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, pos, whence=0):
        result = self._f.seek(pos, whence)
        self._uploaded = self._f.tell()
        return result

    def tell(self):
        return self._f.tell()

    def close(self):
        if not self.closed:
            self._f.close()
            super().close()


def upload_part(client, part_path: Path, label: str):
    """上传单个 part，内置重试，等待云端处理完成，返回 File 对象。"""
    ascii_name = part_path.name.encode("ascii", "ignore").decode("ascii").strip()
    part_num = re.search(r"part\d+", part_path.stem, re.IGNORECASE)
    safe_name = ascii_name or (part_num.group() if part_num else "upload")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            tprint(f"  [{label}] 开始上传{'（重试）' if attempt > 1 else ''}...")
            with _ProgressFile(part_path, label) as pf:
                video_file = client.files.upload(file=pf, config={"display_name": safe_name, "mime_type": "video/mp4"})
            tprint(f"  [{label}] 上传完成，文件 ID: {video_file.name}，等待云端处理...")

            while video_file.state.name == "PROCESSING":
                time.sleep(10)
                video_file = client.files.get(name=video_file.name)

            if video_file.state.name == "FAILED":
                raise RuntimeError(f"[{label}] 云端处理失败")

            tprint(f"  [{label}] 云端处理完成")
            return video_file
        except Exception as e:
            _logger.error(f"[{label}] 上传失败（第 {attempt} 次）", exc_info=True)
            if attempt < MAX_RETRIES:
                tprint(f"  [{label}] 上传失败（第 {attempt} 次）: {e}，{RETRY_DELAY} 秒后重试...")
                time.sleep(RETRY_DELAY)
            else:
                raise


def make_video_part_base64(part_path: Path) -> types.Part:
    """将本地视频文件以原始 bytes 传入 inlineData，SDK 负责 base64 编码。"""
    return types.Part(
        inline_data=types.Blob(mime_type="video/mp4", data=part_path.read_bytes())
    )


def _recover_generated_parts(output_path: Path) -> set:
    """扫描已有输出文件，恢复已生成的片段索引（0-based），避免 Ctrl+C 后重复生成。"""
    if not output_path.exists():
        return set()
    content = output_path.read_text(encoding="utf-8")
    return {int(m.group(1)) - 1 for m in re.finditer(r'<!-- ===== Part (\d+)/\d+ =====', content)}


def _cleanup_cloud_files(client, uploaded_files: dict, video_label: str):
    """删除云端已上传的文件，释放存储配额。"""
    for vf in uploaded_files.values():
        try:
            client.files.delete(name=vf.name)
        except Exception as del_e:
            tprint(f"  [{video_label}] 清理云端缓存失败 (忽略): {del_e}")


def process_video(client, video_stem: str, parts: list[Path], output_path: Path, video_label: str) -> bool:
    """并行上传一个视频的 parts，逐片段调用大模型追加生成，具备断点续传，结束后清理云端文件。"""
    uploaded_files = {}   # p.name -> File，缓存已上传成功的片段
    generated_parts = _recover_generated_parts(output_path)  # 从已有文件恢复，支持 Ctrl+C 后续跑
    if generated_parts:
        tprint(f"[{video_label}] 检测到已生成 {len(generated_parts)} 个片段，将跳过重复处理")

    tprint(f"[{video_label}] 上传模式: {UPLOAD_MODE}")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 1. 上传阶段（files_api 模式才需要预上传）
            if UPLOAD_MODE == "files_api":
                pending_parts = [p for p in parts if p.name not in uploaded_files]
                if pending_parts:
                    tprint(f"\n[{video_label}] 开始上传 {len(pending_parts)} 个片段...")
                    upload_errors = []
                    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as executor:
                        future_to_part = {
                            executor.submit(upload_part, client, p, f"{video_label} {p.name}"): p
                            for p in pending_parts
                        }
                        for future in as_completed(future_to_part):
                            p = future_to_part[future]
                            try:
                                uploaded_files[p.name] = future.result()
                            except Exception as upload_err:
                                tprint(f"[{video_label}] {p.name} 上传失败: {upload_err}")
                                upload_errors.append(upload_err)
                    if upload_errors:
                        raise RuntimeError(f"{len(upload_errors)} 个片段上传失败")
            else:
                tprint(f"\n[{video_label}] 跳过预上传（{UPLOAD_MODE} 模式）")

            # 2. 初始化输出文件（仅首次，重试时已有内容不清空）
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if not generated_parts:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(f"# {video_stem}\n\n")

            # 3. 逐片段调用大模型，已生成的跳过
            tprint(f"[{video_label}] 所有片段就绪，开始逐片段提取知识...")

            for idx, part_path in enumerate(parts):
                if idx in generated_parts:
                    tprint(f"[{video_label}] 片段 {idx + 1}/{len(parts)} 已生成，跳过")
                    continue

                tprint(f"[{video_label}] 正在解析片段 {idx + 1}/{len(parts)} ...")
                part_prompt = (
                    PROMPT_TEXT
                    + f"\n\n注意：这是整个视频的第 {idx + 1}/{len(parts)} 个片段，请提取本片段的完整内容。"
                )

                if UPLOAD_MODE == "files_api":
                    video_part = uploaded_files[part_path.name]
                else:
                    video_part = make_video_part_base64(part_path)

                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[video_part, part_prompt],
                    config={"temperature": 0.1},
                )
                if not response.text:
                    raise RuntimeError(f"API 返回空响应（片段 {idx + 1}/{len(parts)}），将触发重试")
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n<!-- ===== Part {idx + 1}/{len(parts)} ===== -->\n\n")
                    f.write(response.text)
                generated_parts.add(idx)
                has_more = any(i not in generated_parts for i in range(idx + 1, len(parts)))
                if has_more:
                    tprint(f"[{video_label}] 片段 {idx + 1}/{len(parts)} 完成，休眠 {PART_INTERVAL} 秒防 API 限流...")
                    time.sleep(PART_INTERVAL)
                else:
                    tprint(f"[{video_label}] 片段 {idx + 1}/{len(parts)} 完成")

            tprint(f"[{video_label}] 全部分段解析完毕，已保存至: {output_path.name}")
            if UPLOAD_MODE == "files_api":
                _cleanup_cloud_files(client, uploaded_files, video_label)
            return True

        except Exception as e:
            tprint(f"[{video_label}] [错误] 第 {attempt} 次尝试失败: {e}", level="error")
            _logger.error(f"[{video_label}] 第 {attempt} 次尝试失败（完整堆栈）", exc_info=True)
            if attempt < MAX_RETRIES:
                is_rate_limited = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                if is_rate_limited:
                    wait = _parse_retry_delay(e)
                else:
                    wait = RETRY_DELAY
                tprint(f"[{video_label}] {wait} 秒后重试...")
                time.sleep(wait)
            else:
                tprint(f"[{video_label}] 已达最大重试次数，跳过此视频。", level="error")
                _cleanup_cloud_files(client, uploaded_files, video_label)
                return False


def main():
    api_key = os.environ.get("OPENCLAW_GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "未找到 OPENCLAW_GOOGLE_API_KEY 环境变量。\n"
            "请先执行: export OPENCLAW_GOOGLE_API_KEY=your_key_here"
        )

    _setup_logging()
    _logger.info("=" * 60 + " 任务开始")

    caffeinate = subprocess.Popen(["caffeinate", "-i"])
    print("  [防休眠] caffeinate 已启动，电脑不会进入睡眠。")

    try:
        base_url = os.environ.get("GEMINI_BASE_URL", "")
        http_opts = {"timeout": 3600000}  # 防止 generate_content 无限挂死（单位毫秒，= 1h）
        if base_url:
            http_opts["baseUrl"] = base_url
            http_opts["apiVersion"] = os.environ.get("GEMINI_API_VERSION", "v1beta")
        client = genai.Client(api_key=api_key, http_options=http_opts)
        MARKDOWNS_DIR.mkdir(exist_ok=True)

        groups = group_parts(PARTS_DIR)
        if not groups:
            print(f"在 {PARTS_DIR} 下没有找到 *_part*.mp4 文件。")
            return

        progress = load_progress()
        pending = {k: v for k, v in groups.items() if progress.get(k) != "done"}
        done_count = len(groups) - len(pending)

        print(f"共 {len(groups)} 个视频，已完成 {done_count} 个，待处理 {len(pending)} 个。\n")

        for i, (video_stem, parts) in enumerate(pending.items(), 1):
            output_path = MARKDOWNS_DIR / (video_stem + ".md")
            video_label = f"{i}/{len(pending)} {video_stem[:30]}"

            success = process_video(client, video_stem, parts, output_path, video_label)
            progress[video_stem] = "done" if success else "failed"
            save_progress(progress)

        total_done = sum(1 for v in progress.values() if v == "done")
        total_failed = sum(1 for v in progress.values() if v == "failed")
        print(f"\n全部完成。成功: {total_done}，失败: {total_failed}")
    finally:
        caffeinate.terminate()
        print("  [防休眠] caffeinate 已关闭。")


if __name__ == "__main__":
    main()

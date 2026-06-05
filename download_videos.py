"""
小鹅通视频批量下载器
====================
从浏览器提取脚本生成的 JSON 文件读取视频信息，批量下载 m3u8 视频流，
解密 AES-128-CBC 加密的 TS 片段，使用 ffmpeg 合并为 MP4 文件。

用法:
    python download_videos.py [json_file] [options]

    json_file: 浏览器脚本导出的 JSON 文件路径 (默认: zhihu_videos.json)

选项:
    --output-dir DIR    输出目录 (默认: D:/zhihu/zhihu_file/Videos)
    --concurrency N     并发下载线程数 (默认: 3)
    --skip-existing     跳过已存在的视频文件
    --cookie-file FILE  从 Netscape 格式的 cookie 文件读取 cookie
    --ffmpeg PATH       ffmpeg 可执行文件路径

依赖:
    pip install requests pycryptodome

要求:
    - ffmpeg 已安装并可用
    - Python 3.7+

小鹅通加密说明:
    - m3u8 内容可能被 Base64 编码 + 特殊字符替换 (@→1, #→2, $→3, %→4)
    - TS 视频片段使用 AES-128-CBC 加密，IV = 0
    - 密钥从 m3u8 文件中的 URI 地址获取
"""

import argparse
import base64
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from Crypto.Cipher import AES

# ========== 配置 ==========
DEFAULT_OUTPUT_DIR = r"D:\zhihu\zhihu_file\Videos"
DEFAULT_INPUT_FILE = r"D:\zhihu\zhihu_videos.json"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
CHUNK_SIZE = 1024 * 1024  # 1MB for downloads


# ========== 工具函数 ==========
def sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符"""
    name = name.replace("'", "").replace(" ", "_")
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    # 限制长度
    if len(name) > 200:
        name = name[:200]
    return name.strip("_.") or "untitled"


def decode_m3u8_content(content: str) -> str:
    """
    解码小鹅通加密的 m3u8 内容。
    加密方式: Base64 编码 + 特殊字符替换 (@→1, #→2, $→3, %→4)
    """
    # 如果内容看起来像是标准的 m3u8（包含 #EXTM3U），直接返回
    if "#EXTM3U" in content:
        return content

    try:
        # 先进行字符替换逆操作
        decoded = content.replace("@", "1").replace("#", "2").replace("$", "3").replace("%", "4")
        # Base64 解码
        raw = base64.b64decode(decoded).decode("utf-8", errors="ignore")
        if "#EXTM3U" in raw:
            return raw
        return content  # 解码失败，返回原始内容
    except Exception:
        return content  # 如果解码失败，可能已经是明文的了


def try_decode_m3u8_binary(content: bytes) -> str:
    """尝试解码二进制 m3u8 内容"""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="ignore")

    return decode_m3u8_content(text)


# ========== M3U8 解析 ==========
def parse_m3u8(m3u8_content: str, base_url: str) -> dict:
    """
    解析 M3U8 播放列表，返回：
    {
        "ts_urls": [...],
        "key_url": "..." or None,
        "key_iv": b"..." or None,
        "is_master": bool,
        "variants": [...],  # 如果是 master playlist
    }
    """
    lines = m3u8_content.strip().split("\n")
    result = {
        "ts_urls": [],
        "key_url": None,
        "key_iv": None,
        "is_master": False,
        "variants": [],
        "duration": 0,
    }

    current_key_url = None
    current_key_iv = None

    for line in lines:
        line = line.strip()

        # 检测是否为 master playlist
        if line.startswith("#EXT-X-STREAM-INF"):
            result["is_master"] = True
            # 提取分辨率信息
            resolution = re.search(r"RESOLUTION=(\d+x\d+)", line)
            bandwidth = re.search(r"BANDWIDTH=(\d+)", line)
            result["variants"].append({
                "resolution": resolution.group(1) if resolution else "unknown",
                "bandwidth": int(bandwidth.group(1)) if bandwidth else 0,
            })
            continue

        # 解析加密密钥
        if line.startswith("#EXT-X-KEY"):
            uri_match = re.search(r'URI="([^"]*)"', line)
            if uri_match:
                current_key_url = uri_match.group(1)
                # 处理相对路径
                if current_key_url and not current_key_url.startswith("http"):
                    current_key_url = urljoin(base_url, current_key_url)

            iv_match = re.search(r"IV=0x([0-9a-fA-F]+)", line)
            if iv_match:
                current_key_iv = bytes.fromhex(iv_match.group(1))
            else:
                current_key_iv = b"\x00" * 16  # 默认 IV = 0

        # 提取 TS 片段 URL
        if line and not line.startswith("#"):
            ts_url = line
            if not ts_url.startswith("http"):
                ts_url = urljoin(base_url, ts_url)
            result["ts_urls"].append(ts_url)

        # 计算总时长
        if line.startswith("#EXTINF"):
            duration_match = re.search(r"#EXTINF:([\d.]+)", line)
            if duration_match:
                result["duration"] += float(duration_match.group(1))

    # 设置最终的 key 信息
    result["key_url"] = current_key_url
    result["key_iv"] = current_key_iv

    return result


def get_best_variant_url(m3u8_content: str, base_url: str) -> str:
    """从 master playlist 中选择最高质量的变体 URL"""
    lines = m3u8_content.strip().split("\n")
    variants = []

    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            resolution = re.search(r"RESOLUTION=(\d+x(\d+))", line)
            bandwidth = re.search(r"BANDWIDTH=(\d+)", line)
            height = int(resolution.group(2)) if resolution else 0
            bw = int(bandwidth.group(1)) if bandwidth else 0

            # 下一行是变体 URL
            if i + 1 < len(lines):
                variant_url = lines[i + 1].strip()
                if not variant_url.startswith("http"):
                    variant_url = urljoin(base_url, variant_url)
                variants.append({"url": variant_url, "height": height, "bandwidth": bw})

    if not variants:
        return base_url

    # 选择最高分辨率的变体
    variants.sort(key=lambda v: (v["height"], v["bandwidth"]), reverse=True)
    best = variants[0]
    print(f"   📺 选择画质: {best['height']}p (带宽: {best['bandwidth']})")
    return best["url"]


# ========== 下载器 ==========
class VideoDownloader:
    def __init__(self, output_dir: str, concurrency: int = 3, skip_existing: bool = True,
                 cookies: dict = None, ffmpeg_path: str = "ffmpeg"):
        self.output_dir = Path(output_dir)
        self.concurrency = concurrency
        self.skip_existing = skip_existing
        self.cookies = cookies or {}
        self.ffmpeg_path = ffmpeg_path
        self.session = requests.Session()

        if cookies:
            for key, value in cookies.items():
                self.session.cookies.set(key, value)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 通用的请求头
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        })

    def _http_get(self, url: str, retries: int = MAX_RETRIES, **kwargs) -> requests.Response:
        """带重试的 HTTP GET 请求"""
        for attempt in range(retries):
            try:
                kwargs.setdefault("timeout", REQUEST_TIMEOUT)
                resp = self.session.get(url, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"   ⚠️ 请求失败 (尝试 {attempt + 1}/{retries}): {e}, {wait}s 后重试...")
                    time.sleep(wait)
                else:
                    raise

    def _http_post(self, url: str, retries: int = MAX_RETRIES, **kwargs) -> requests.Response:
        """带重试的 HTTP POST 请求"""
        for attempt in range(retries):
            try:
                kwargs.setdefault("timeout", REQUEST_TIMEOUT)
                resp = self.session.post(url, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"   ⚠️ 请求失败 (尝试 {attempt + 1}/{retries}): {e}, {wait}s 后重试...")
                    time.sleep(wait)
                else:
                    raise

    def get_m3u8_content(self, m3u8_url: str) -> str:
        """下载并解码 m3u8 内容"""
        resp = self._http_get(m3u8_url)
        content = try_decode_m3u8_binary(resp.content)
        return content

    def download_key(self, key_url: str) -> bytes:
        """下载 AES 解密密钥"""
        if not key_url:
            return None
        resp = self._http_get(key_url)
        return resp.content

    def download_and_decrypt_ts(self, task: tuple) -> bool:
        """下载单个 TS 片段并解密"""
        index, ts_url, key, iv, temp_dir = task
        ts_path = temp_dir / f"{index:06d}.ts"

        if ts_path.exists():
            return True

        try:
            resp = self._http_get(ts_url)
            data = resp.content

            if key:
                cipher = AES.new(key, AES.MODE_CBC, iv)
                data = cipher.decrypt(data)
                # 去除 PKCS7 padding
                if data:
                    padding_len = data[-1]
                    if 0 < padding_len <= 16:
                        data = data[:-padding_len]

            ts_path.write_bytes(data)
            return True
        except Exception as e:
            print(f"   ❌ TS 片段 [{index}] 下载失败: {e}")
            return False

    def merge_with_ffmpeg(self, temp_dir: Path, output_path: Path, ts_count: int) -> bool:
        """使用 ffmpeg 合并 TS 片段"""
        # 创建 concat 文件列表
        concat_file = temp_dir / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for i in range(ts_count):
                ts_file = temp_dir / f"{i:06d}.ts"
                if ts_file.exists():
                    f.write(f"file '{ts_file.as_posix()}'\n")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            cmd = [
                self.ffmpeg_path, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                str(output_path),
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            return True
        except subprocess.CalledProcessError as e:
            print(f"   ⚠️ FFmpeg 合并失败: {e.stderr.decode() if e.stderr else e}")
            # 尝试备用方案：不使用 bitstream filter
            try:
                cmd2 = [
                    self.ffmpeg_path, "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_file),
                    "-c", "copy",
                    str(output_path),
                ]
                subprocess.run(cmd2, check=True, capture_output=True, timeout=600)
                return True
            except subprocess.CalledProcessError as e2:
                print(f"   ❌ 备用合并也失败: {e2.stderr.decode() if e2.stderr else e2}")
                return False
        except subprocess.TimeoutExpired:
            print(f"   ❌ FFmpeg 合并超时")
            return False

    def download_video(self, video_info: dict, index: int, total: int) -> bool:
        """下载单个视频"""
        title = video_info.get("title", f"video_{index}")
        resource_id = video_info.get("resource_id", "unknown")
        play_url = video_info.get("play_url", "")
        chapter_title = video_info.get("chapter_title", "")

        # 构建输出文件名
        safe_title = sanitize_filename(title)
        if chapter_title:
            safe_chapter = sanitize_filename(chapter_title)
            filename = f"{index:03d}_{safe_chapter}_{safe_title}.mp4"
        else:
            filename = f"{index:03d}_{safe_title}.mp4"

        output_path = self.output_dir / filename

        # 检查是否已存在
        if self.skip_existing and output_path.exists() and output_path.stat().st_size > 0:
            print(f"[{index}/{total}] ✅ 已存在: {filename}")
            return True

        print(f"[{index}/{total}] 📥 下载: {filename}")

        if not play_url:
            print(f"   ⚠️ 无播放 URL，跳过")
            return False

        # 如果 play_url 是 JSON 字符串 (来自 encrypted 字段)，先解析
        if isinstance(play_url, str) and play_url.startswith("{"):
            try:
                play_data = json.loads(play_url)
                play_url = play_data.get("url", play_url)
            except json.JSONDecodeError:
                pass

        temp_dir = self.output_dir / f".temp_{index:03d}_{safe_title[:50]}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. 获取 m3u8 内容
            print(f"   📡 获取 m3u8: {play_url[:80]}...")
            m3u8_content = self.get_m3u8_content(play_url)

            # 2. 检查是否为 master playlist
            if "#EXT-X-STREAM-INF" in m3u8_content:
                print(f"   📋 检测到 master playlist，选择最佳画质...")
                best_url = get_best_variant_url(m3u8_content, play_url)
                m3u8_content = self.get_m3u8_content(best_url)

            # 3. 解析 m3u8
            parsed = parse_m3u8(m3u8_content, play_url)

            if not parsed["ts_urls"]:
                # 尝试直接保存 m3u8 文件（有些视频可能是单文件）
                print(f"   ⚠️ 未找到 TS 片段，尝试直接下载...")
                resp = self._http_get(play_url)
                output_path.write_bytes(resp.content)
                print(f"   ✅ 直接下载完成: {output_path.name}")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return True

            ts_count = len(parsed["ts_urls"])
            print(f"   🎬 共 {ts_count} 个 TS 片段, 时长: {parsed['duration']:.0f}s")

            # 4. 获取解密密钥
            key = None
            iv = b"\x00" * 16
            if parsed["key_url"]:
                print(f"   🔑 下载解密密钥...")
                try:
                    key = self.download_key(parsed["key_url"])
                    iv = parsed["key_iv"] or iv
                    print(f"   ✅ 密钥长度: {len(key)} bytes")
                except Exception as e:
                    print(f"   ⚠️ 密钥下载失败: {e}")

            # 5. 并发下载 TS 片段
            tasks = [
                (i, url, key, iv, temp_dir)
                for i, url in enumerate(parsed["ts_urls"])
            ]

            print(f"   📥 下载 {ts_count} 个 TS 片段 (并发: {self.concurrency})...")
            failed = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                futures = {
                    executor.submit(self.download_and_decrypt_ts, task): task[0]
                    for task in tasks
                }

                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    index_num = futures[future]
                    if not future.result():
                        failed.append(index_num)
                    completed += 1
                    if completed % 50 == 0 or completed == ts_count:
                        print(f"   📊 TS 下载进度: {completed}/{ts_count}")

            if failed:
                print(f"   ⚠️ {len(failed)} 个 TS 片段下载失败: {failed[:10]}...")

            # 6. 合并 TS 片段
            print(f"   🔧 合并视频...")
            if self.merge_with_ffmpeg(temp_dir, output_path, ts_count):
                file_size = output_path.stat().st_size
                print(f"   ✅ 完成: {output_path.name} ({file_size / 1024 / 1024:.1f} MB)")
                # 清理临时目录
                shutil.rmtree(temp_dir, ignore_errors=True)
                return True
            else:
                print(f"   ❌ 合并失败")
                return False

        except Exception as e:
            print(f"   ❌ 下载失败: {e}")
            return False

    def download_all(self, video_list: list) -> dict:
        """批量下载所有视频"""
        total = len(video_list)
        print(f"\n🎬 开始批量下载 {total} 个视频")
        print(f"📁 输出目录: {self.output_dir}")
        print(f"🔧 并发数: {self.concurrency}")
        print(f"📌 跳过已存在: {self.skip_existing}")
        print("=" * 60)

        results = {"success": 0, "failed": 0, "skipped": 0, "errors": []}
        start_time = time.time()

        for i, video in enumerate(video_list, 1):
            video_start = time.time()

            # 检查是否已存在（在 download_video 之前快速检查）
            title = video.get("title", f"video_{i}")
            safe_title = sanitize_filename(title)
            chapter = sanitize_filename(video.get("chapter_title", ""))
            filename = f"{i:03d}_{chapter}_{safe_title}.mp4" if chapter else f"{i:03d}_{safe_title}.mp4"
            output_path = self.output_dir / filename

            if self.skip_existing and output_path.exists() and output_path.stat().st_size > 0:
                results["skipped"] += 1
                print(f"[{i}/{total}] ⏭️ 已存在: {filename}")
                continue

            try:
                success = self.download_video(video, i, total)
                if success:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({
                        "index": i,
                        "title": title,
                        "resource_id": video.get("resource_id"),
                        "error": "下载失败",
                    })
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "index": i,
                    "title": title,
                    "resource_id": video.get("resource_id"),
                    "error": str(e),
                })
                print(f"[{i}/{total}] ❌ 异常: {e}")

            elapsed = time.time() - video_start
            if elapsed > 1:
                print(f"   ⏱️ 耗时: {elapsed:.1f}s")

        total_time = time.time() - start_time
        print("\n" + "=" * 60)
        print(f"📊 下载完成!")
        print(f"   ✅ 成功: {results['success']}")
        print(f"   ❌ 失败: {results['failed']}")
        print(f"   ⏭️  跳过: {results['skipped']}")
        print(f"   ⏱️ 总耗时: {total_time / 60:.1f} 分钟")
        if results["errors"]:
            print(f"\n⚠️ 失败详情:")
            for err in results["errors"][:20]:
                print(f"   [{err['index']}] {err['title']}: {err['error']}")

        # 保存失败列表供重试
        if results["errors"]:
            retry_file = self.output_dir / "failed_videos.json"
            with open(retry_file, "w", encoding="utf-8") as f:
                json.dump(results["errors"], f, ensure_ascii=False, indent=2)
            print(f"\n💾 失败列表已保存到: {retry_file}")

        return results


# ========== Cookie 文件解析 ==========
def parse_cookie_file(filepath: str) -> dict:
    """解析 Netscape 格式的 cookie 文件"""
    cookies = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    domain = parts[0]
                    name = parts[5]
                    value = parts[6]
                    cookies[name] = value
    except Exception as e:
        print(f"⚠️ Cookie 文件解析失败: {e}")

    return cookies


# ========== 主函数 ==========
def main():
    parser = argparse.ArgumentParser(
        description="小鹅通视频批量下载器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python download_videos.py
    python download_videos.py zhihu_videos.json --concurrency 5
    python download_videos.py zhihu_videos.json --skip-existing --concurrency 8
    python download_videos.py zhihu_videos.json --cookie-file cookies.txt
        """,
    )
    parser.add_argument(
        "json_file", nargs="?", default=DEFAULT_INPUT_FILE,
        help=f"视频信息 JSON 文件路径 (默认: {DEFAULT_INPUT_FILE})"
    )
    parser.add_argument(
        "--output-dir", "-o", default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--concurrency", "-c", type=int, default=3,
        help="并发下载线程数 (默认: 3)"
    )
    parser.add_argument(
        "--skip-existing", "-s", action="store_true", default=True,
        help="跳过已存在的视频文件 (默认启用)"
    )
    parser.add_argument(
        "--no-skip", dest="skip_existing", action="store_false",
        help="不跳过已存在的视频，强制重新下载"
    )
    parser.add_argument(
        "--cookie-file", default=None,
        help="Netscape 格式的 cookie 文件路径"
    )
    parser.add_argument(
        "--ffmpeg", default="ffmpeg",
        help="ffmpeg 可执行文件路径 (默认: ffmpeg)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅解析和显示视频列表，不实际下载"
    )

    args = parser.parse_args()

    # 检查 JSON 文件
    if not os.path.exists(args.json_file):
        print(f"❌ JSON 文件不存在: {args.json_file}")
        print(f"\n请先运行浏览器提取脚本 (extract_videos.js) 生成视频信息文件。")
        print(f"或指定正确的文件路径: python download_videos.py <path_to_json>")
        sys.exit(1)

    # 检查 ffmpeg
    if not args.dry_run:
        ffmpeg_available = shutil.which(args.ffmpeg) is not None
        if not ffmpeg_available:
            print(f"❌ 找不到 ffmpeg: {args.ffmpeg}")
            print(f"\n请安装 ffmpeg 或使用 --ffmpeg 参数指定路径。")
            print(f"下载地址: https://ffmpeg.org/download.html")
            print(f"\n或使用 --dry-run 先预览视频列表。")
            sys.exit(1)

    # 读取视频信息
    print(f"📄 读取视频信息: {args.json_file}")
    with open(args.json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    videos = data.get("videos", [])
    if not videos:
        print("❌ JSON 文件中没有视频数据")
        print("请确保 JSON 文件包含 'videos' 数组")
        sys.exit(1)

    # 过滤掉没有 play_url 的视频 (如果有 resource_id 则保留)
    valid_videos = [v for v in videos if v.get("play_url") or v.get("resource_id")]

    print(f"📋 课程标题: {data.get('course_title', '未知')}")
    print(f"📋 导出时间: {data.get('export_time', '未知')}")
    print(f"📋 视频总数: {len(videos)}")
    print(f"📋 可处理视频: {len(valid_videos)}")

    # 检查是否有播放 URL
    has_play_urls = any(v.get("play_url") for v in valid_videos)
    if not has_play_urls:
        print("\n⚠️ 视频列表中没有 play_url 字段！")
        print("这说明浏览器提取脚本未能获取视频播放地址。")
        print("\n可能的原因:")
        print("   1. 课程页面需要先登录")
        print("   2. 需要先在页面点击播放一个视频，触发 API 调用")
        print("   3. 页面 API 路径有所不同，需要调试")
        print("\n请重新运行浏览器提取脚本 (extract_videos.js)，")
        print("确保已经登录并在页面播放了至少一个视频。")

        if args.dry_run:
            print("\n📋 视频列表预览:")
            for i, v in enumerate(videos[:20], 1):
                print(f"   [{i}] {v.get('title', '未知')} (resource_id: {v.get('resource_id', 'N/A')})")
            if len(videos) > 20:
                print(f"   ... 还有 {len(videos) - 20} 个")
        sys.exit(1)

    # 解析 cookies
    cookies = {}
    if args.cookie_file:
        print(f"🍪 读取 Cookie 文件: {args.cookie_file}")
        cookies = parse_cookie_file(args.cookie_file)

    if args.dry_run:
        print(f"\n📋 视频列表预览 (共 {len(valid_videos)} 个):")
        print("-" * 60)
        for i, v in enumerate(valid_videos[:30], 1):
            title = v.get("title", "未知")
            play_url = v.get("play_url", "N/A")
            print(f"  [{i:03d}] {title[:60]}")
            print(f"         URL: {str(play_url)[:80]}")
        if len(valid_videos) > 30:
            print(f"  ... 还有 {len(valid_videos) - 30} 个")
        return

    # 开始下载
    downloader = VideoDownloader(
        output_dir=args.output_dir,
        concurrency=args.concurrency,
        skip_existing=args.skip_existing,
        cookies=cookies,
        ffmpeg_path=args.ffmpeg,
    )

    results = downloader.download_all(valid_videos)

    # 最终统计
    total_files = len(list(Path(args.output_dir).glob("*.mp4")))
    print(f"\n📁 输出目录共有 {total_files} 个 MP4 文件: {args.output_dir}")


if __name__ == "__main__":
    main()

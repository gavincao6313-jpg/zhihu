#!/usr/bin/env python3
"""
知乎训练营课程目录回放批量下载

工作原理：
  1. 加载 zhihu_auth_state.json 登录态
  2. Playwright 打开课程页，拦截 API 响应自动发现课程目录
  3. 逐个打开每个视频页，拦截 m3u8/视频 URL
  4. ffmpeg 下载并保存为 MP4

依赖：
  pip install playwright requests
  playwright install chromium
  ffmpeg 在 PATH 中（Windows: https://ffmpeg.org/download.html）

用法：
  python scripts/zhihu_course_replay_downloader.py
  python scripts/zhihu_course_replay_downloader.py --url "https://www.zhihu.com/xen/market/training/training-video/..."
  python scripts/zhihu_course_replay_downloader.py --dry-run
  python scripts/zhihu_course_replay_downloader.py --help
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR  = Path(__file__).parent.parent
AUTH_FILE = ROOT_DIR / "zhihu_auth_state.json"
OUT_DIR   = Path(r"E:\AI产品经理课")

DEFAULT_COURSE_URL = (
    "https://www.zhihu.com/xen/market/training/training-video"
    "/1972723265349902377/1982458776650011941"
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_VIDEO_URL_MARKERS = (
    ".m3u8", "vzuu.com", "vdn", "video.zhihu.com",
    "play_url", "hls", "stream",
)

_CATALOG_URL_MARKERS = (
    "/training/", "catalog", "chapter", "section",
    "syllabus", "course", "replay",
)


# ── 工具函数 ──────────────────────────────────────────────────────

def extract_training_id(url: str) -> str:
    m = re.search(r"/training-video/(\d+)", url)
    if not m:
        raise ValueError(f"无法从 URL 中提取 training_id: {url}")
    return m.group(1)


def safe_name(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    return s.strip()[:80] or "untitled"


def cookies_to_header(storage_state: dict) -> str:
    cookies = storage_state.get("cookies", [])
    return "; ".join(
        f"{c['name']}={c['value']}"
        for c in cookies
        if "zhihu.com" in c.get("domain", "")
    )


def load_progress(prog_file: Path) -> set:
    if prog_file.exists():
        return set(json.loads(prog_file.read_text("utf-8")).get("done", []))
    return set()


def save_progress(prog_file: Path, done: set) -> None:
    prog_file.parent.mkdir(parents=True, exist_ok=True)
    prog_file.write_text(
        json.dumps({"done": sorted(done)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 递归提取视频条目 ──────────────────────────────────────────────

def _extract_videos(data: object, depth: int = 0) -> list:
    if depth > 8 or not data:
        return []
    results = []
    if isinstance(data, list):
        for item in data:
            results.extend(_extract_videos(item, depth + 1))
        return results
    if not isinstance(data, dict):
        return []

    type_ = str(data.get("type", "")).lower()
    has_video_field = any(k in data for k in (
        "video_token", "video_id", "zv_id", "play_url",
        "video_url", "replay_url", "attachment_id",
    ))
    has_title = any(k in data for k in ("title", "name", "display_title"))

    if (has_video_field or "video" in type_) and has_title:
        title = (data.get("title") or data.get("name")
                 or data.get("display_title") or "")
        token = (data.get("video_token") or data.get("video_id")
                 or data.get("zv_id") or "")
        vid_id = str(data.get("id") or data.get("video_item_id") or "")
        play_url = (data.get("play_url") or data.get("video_url")
                    or data.get("replay_url") or "")
        if title:
            results.append({
                "title":         title,
                "video_token":   str(token),
                "video_item_id": vid_id,
                "play_url":      play_url,
            })

    for key in ("data", "list", "items", "sections", "chapters",
                "videos", "contents", "catalog", "children",
                "records", "course_list", "replay_list"):
        child = data.get(key)
        if child:
            results.extend(_extract_videos(child, depth + 1))

    return results


# ── Playwright 探测 ───────────────────────────────────────────────

def probe_course(course_url: str, auth_file: Path, timeout_s: int = 120):
    """
    打开课程页，拦截网络请求，返回：
      catalog_videos: 课程目录视频列表
      video_m3u8:     {video_item_id: stream_url}
    """
    from playwright.sync_api import sync_playwright

    catalog_videos = []
    catalog_found = [False]
    video_m3u8 = {}
    current_vid_id = [""]

    def on_response(response) -> None:
        url = response.url
        if response.status != 200:
            return

        if (not catalog_found[0]
                and "zhihu.com" in url
                and any(k in url for k in _CATALOG_URL_MARKERS)):
            try:
                videos = _extract_videos(json.loads(response.text()))
                if len(videos) >= 2:
                    print(f"  [catalog] {url.split('?')[0]} → {len(videos)} 个视频")
                    catalog_videos.extend(videos)
                    catalog_found[0] = True
            except Exception:
                pass

        if any(k in url.lower() for k in _VIDEO_URL_MARKERS):
            key = current_vid_id[0]
            if key and key not in video_m3u8:
                video_m3u8[key] = url
                print(f"  [stream] {key} → {url[:80]}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        storage = str(auth_file) if auth_file.exists() else None
        ctx = browser.new_context(
            user_agent=UA,
            storage_state=storage,
            viewport={"width": 1280, "height": 800},
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        page = ctx.new_page()
        page.on("response", on_response)

        print(f"打开课程页: {course_url}")
        try:
            page.goto(course_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"  [warn] 页面加载: {e}")

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(2)
            if catalog_found[0]:
                break

        if not catalog_found[0]:
            print("  [warn] API 未返回目录，尝试 DOM 提取...")
            training_id = extract_training_id(course_url)
            try:
                links = page.eval_on_selector_all(
                    f"a[href*='/training-video/{training_id}/']",
                    "els => els.map(e => ({href: e.href, text: e.innerText.trim()}))",
                )
                seen = set()
                for lk in links:
                    href = lk.get("href", "")
                    m = re.search(r"/training-video/\d+/(\d+)", href)
                    if m and m.group(1) not in seen:
                        vid = m.group(1)
                        seen.add(vid)
                        catalog_videos.append({
                            "title":         lk.get("text") or vid,
                            "video_token":   "",
                            "video_item_id": vid,
                            "play_url":      "",
                            "page_url":      href,
                        })
                print(f"  DOM 提取 {len(catalog_videos)} 个链接")
            except Exception as e:
                print(f"  DOM 提取失败: {e}")

        training_id = extract_training_id(course_url)
        base = (
            "https://www.zhihu.com/xen/market/training/training-video/"
            + training_id
        )

        for idx, video in enumerate(catalog_videos):
            vid_id = video.get("video_item_id") or video.get("video_token") or ""
            if not vid_id:
                continue
            if video.get("play_url") or vid_id in video_m3u8:
                continue

            page_url = video.get("page_url") or f"{base}/{vid_id}"
            title_short = video["title"][:40]
            print(f"  [{idx+1}/{len(catalog_videos)}] {title_short}")
            current_vid_id[0] = vid_id

            vpage = ctx.new_page()
            vpage.on("response", on_response)
            try:
                vpage.goto(page_url, wait_until="domcontentloaded", timeout=45_000)
                time.sleep(8)
            except Exception as e:
                print(f"    [warn] {e}")
            finally:
                vpage.close()

            current_vid_id[0] = ""
            time.sleep(1)

        browser.close()

    return catalog_videos, video_m3u8


# ── ffmpeg 下载 ───────────────────────────────────────────────────

def ffmpeg_download(stream_url: str, dest: Path, cookie_str: str) -> bool:
    if dest.exists() and dest.stat().st_size > 512 * 1024:
        print(f"    [skip] 已存在: {dest.name}")
        return True

    tmp = dest.with_suffix(".tmp.mp4")
    headers = (
        f"User-Agent: {UA}\r\n"
        f"Referer: https://www.zhihu.com/\r\n"
    )
    if cookie_str:
        headers += f"Cookie: {cookie_str}\r\n"

    cmd = [
        "ffmpeg", "-y",
        "-headers", headers,
        "-i", stream_url,
        "-c", "copy",
        "-movflags", "+faststart",
        str(tmp),
    ]
    print(f"    ffmpeg: {dest.name}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.rename(dest)
            mb = dest.stat().st_size / 1024 / 1024
            print(f"    完成: {dest.name} ({mb:.1f} MB)")
            return True
        err = (result.stderr or "")[-600:]
        print(f"    [err] ffmpeg 失败:\n{err}")
        if tmp.exists():
            tmp.unlink()
        return False
    except subprocess.TimeoutExpired:
        print("    [err] 下载超时（2 小时）")
        if tmp.exists():
            tmp.unlink()
        return False
    except FileNotFoundError:
        print("[fatal] 未找到 ffmpeg，请安装并加入 PATH")
        print("  Windows: https://ffmpeg.org/download.html → 解压 → 将 bin/ 加入系统 PATH")
        sys.exit(1)


# ── 主流程 ────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="知乎训练营课程回放批量下载")
    ap.add_argument("--url",     default=DEFAULT_COURSE_URL, help="课程视频页 URL")
    ap.add_argument("--out",     default=str(OUT_DIR),       help="输出目录")
    ap.add_argument("--dry-run", action="store_true",         help="仅列出视频，不下载")
    ap.add_argument("--delay",   type=float, default=2.0,    help="下载间隔（秒）")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    prog_file = out_dir / ".progress.json"

    if not AUTH_FILE.exists():
        print(f"[warn] 未找到 {AUTH_FILE}")
        print("  请先运行: python login_save_auth.py  （扫码登录知乎）")
        print()

    cookie_str = ""
    if AUTH_FILE.exists():
        try:
            state = json.loads(AUTH_FILE.read_text("utf-8"))
            cookie_str = cookies_to_header(state)
        except Exception as e:
            print(f"[warn] 读取 auth: {e}")

    print("=== 步骤 1: 发现课程目录 ===")
    catalog_videos, video_m3u8 = probe_course(args.url, AUTH_FILE)

    if not catalog_videos:
        print("[error] 未能获取课程目录，请检查：")
        print("  1. zhihu_auth_state.json 存在且未过期（重新运行 login_save_auth.py）")
        print("  2. 课程 URL 正确")
        sys.exit(1)

    print(f"\n共 {len(catalog_videos)} 个视频：")
    for i, v in enumerate(catalog_videos, 1):
        vid_id = v.get("video_item_id") or v.get("video_token") or "?"
        has_url = bool(v.get("play_url") or video_m3u8.get(vid_id))
        mark = "OK" if has_url else "?"
        print(f"  {i:3}. [{mark}] {v['title']}")

    if args.dry_run:
        print("\n[dry-run] 仅列出，不下载。")
        return

    print("\n=== 步骤 2: 批量下载 ===")
    done = load_progress(prog_file)
    ok = fail = skip = 0
    training_id = extract_training_id(args.url)

    for i, video in enumerate(catalog_videos, 1):
        title  = safe_name(video["title"] or f"video_{i:03d}")
        vid_id = video.get("video_item_id") or video.get("video_token") or ""
        dest   = out_dir / f"{i:03d}_{title}.mp4"

        print(f"\n[{i}/{len(catalog_videos)}] {title}")

        if title in done:
            print("  [skip] 已下载")
            skip += 1
            continue

        stream_url = video.get("play_url") or video_m3u8.get(vid_id, "")

        if not stream_url:
            print(f"  [fail] 无播放地址（vid_id={vid_id}）")
            fail += 1
            continue

        if ffmpeg_download(stream_url, dest, cookie_str):
            ok += 1
            done.add(title)
            save_progress(prog_file, done)
        else:
            fail += 1

        if i < len(catalog_videos):
            time.sleep(args.delay)

    print(f"\n完成：成功 {ok}  跳过 {skip}  失败 {fail}")
    print(f"文件保存在：{out_dir.resolve()}")


if __name__ == "__main__":
    main()

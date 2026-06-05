"""
知乎训练营视频下载器 v2
======================
使用已提取的 catalog.json + Playwright auth state
逐个打开视频页 → 拦截 m3u8 流 → ffmpeg 下载

用法: python zhihu_download_v2.py
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

CATALOG_FILE = Path(r"D:/zhihu/catalog.json")
AUTH_FILE = Path(r"D:/zhihu/zhihu_auth_state.json")
OUTPUT_DIR = Path(r"E:\AI产品经理课")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
COURSE_ID = "1972723265349902377"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s)[:80]


def main():
    catalog = json.loads(CATALOG_FILE.read_text("utf-8"))
    print(f"课程目录: {len(catalog)} 节")

    # 读 auth
    auth = json.loads(AUTH_FILE.read_text("utf-8"))
    cookie_str = "; ".join(
        f"{c['name']}={c['value']}"
        for c in auth["cookies"]
        if "zhihu.com" in c.get("domain", "")
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            storage_state=str(AUTH_FILE),
            user_agent=UA,
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
        """)

        # 收集每个视频的流 URL
        stream_urls = {}
        found_count = 0

        for idx, video in enumerate(catalog, 1):
            section_id = video["section_id"]
            title = video["title"]
            video_url = f"https://www.zhihu.com/xen/market/training/training-video/{COURSE_ID}/{section_id}"

            print(f"\n[{idx}/{len(catalog)}] {title[:50]}")

            page = ctx.new_page()

            # 拦截视频流请求（mp4/m3u8/ts/vzuu）
            captured = []
            def on_request(req):
                url = req.url
                if any(k in url for k in (".m3u8", ".ts", ".mp4", "vzuu.com", "vdn")):
                    captured.append(url)

            page.on("request", on_request)

            try:
                page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
                time.sleep(2)

                # 点击视频元素触发播放
                video_el = page.query_selector("video")
                if video_el:
                    try:
                        video_el.click()
                    except Exception:
                        page.mouse.click(640, 400)

                # 等待视频流请求出现
                for _ in range(25):
                    time.sleep(1)
                    if captured:
                        break

                if captured:
                    # 优先选 mp4（直接链接），其次 m3u8
                    mp4_urls = [u for u in captured if ".mp4" in u and "vzuu.com" in u]
                    m3u8_urls = [u for u in captured if ".m3u8" in u]
                    if mp4_urls:
                        stream_urls[section_id] = mp4_urls[0]
                        found_count += 1
                        print(f"  [MP4] {mp4_urls[0][:100]}")
                    elif m3u8_urls:
                        stream_urls[section_id] = m3u8_urls[0]
                        found_count += 1
                        print(f"  [M3U8] {m3u8_urls[0][:100]}")
                    else:
                        stream_urls[section_id] = captured[0]
                        found_count += 1
                        print(f"  [RAW] {captured[0][:100]}")
                else:
                    print(f"  [NO STREAM] 可能无权限或未购买")
            except Exception as e:
                print(f"  [ERR] {e}")
            finally:
                page.close()

            if idx % 10 == 0:
                print(f"  进度: {idx}/{len(catalog)}, 找到 {found_count} 个流")

        browser.close()

    print(f"\n找到 {found_count}/{len(catalog)} 个视频流")
    if found_count == 0:
        print("FAIL: 未找到任何流 URL，账号可能未购买此课程")
        sys.exit(1)

    # 下载阶段
    print("\n开始 ffmpeg 下载...")
    ok = fail = skip = 0

    for idx, video in enumerate(catalog, 1):
        section_id = video["section_id"]
        title = safe_name(video["title"])
        dest = OUTPUT_DIR / f"{idx:03d}_{title}.mp4"

        stream_url = stream_urls.get(section_id, "")
        if not stream_url:
            fail += 1
            continue

        if dest.exists() and dest.stat().st_size > 10 * 1024 * 1024:
            print(f"[{idx}/{len(catalog)}] SKIP {title[:50]}")
            skip += 1
            continue

        print(f"[{idx}/{len(catalog)}] {title[:50]}")
        tmp = dest.with_suffix(".tmp.mp4")

        headers = (
            f"User-Agent: {UA}\r\n"
            f"Referer: https://www.zhihu.com/\r\n"
            f"Cookie: {cookie_str}\r\n"
        )

        cmd = [
            "ffmpeg", "-y",
            "-headers", headers,
            "-i", stream_url,
            "-c", "copy",
            "-movflags", "+faststart",
            str(tmp),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
            if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                tmp.rename(dest)
                mb = dest.stat().st_size / 1024 / 1024
                print(f"  OK {mb:.0f}MB")
                ok += 1
            else:
                print(f"  FAIL: {result.stderr[-300:]}")
                fail += 1
                if tmp.exists():
                    tmp.unlink()
        except subprocess.TimeoutExpired:
            print("  TIMEOUT")
            fail += 1
        except Exception as e:
            print(f"  ERR: {e}")
            fail += 1

    print(f"\nDONE! ok={ok} skip={skip} fail={fail}")
    print(f"Dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

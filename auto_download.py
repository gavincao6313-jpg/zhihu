"""
小鹅通全自动视频批量下载器 v5
==============================
支持两种资源类型:
- type=4 直播回放 (l_xxx): get_lookback_list API
- type=3 视频 (v_xxx): 导航到视频页 → getPlayUrl API → 提取m3u8

用法: python auto_download.py
"""

import asyncio
import base64
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
from Crypto.Cipher import AES
from playwright.async_api import async_playwright

# ========== 配置 ==========
COURSE_URL = "https://appzl5apwz41977.h5.xet.pomoho.com/p/course/column/p_66f385aee4b0694c3c4b058c?product_id=p_62ee31c5e4b050af23a5b3e7"
PRODUCT_ID = "p_62ee31c5e4b050af23a5b3e7"
COLUMN_ID = "p_66f385aee4b0694c3c4b058c"
APP_ID = "appzl5apwz41977"
BASE_URL = "https://appzl5apwz41977.h5.xet.pomoho.com"
OUTPUT_DIR = Path(r"E:\超凡会\p_66f385ae")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CONCURRENCY = 5


# ========== 工具函数 ==========
def sanitize_filename(name):
    name = name.replace("'", "").replace(" ", "_")
    for char in '<>:"/\\|?*':
        name = name.replace(char, "_")
    return name.strip("_.")[:200] or "untitled"


def decode_m3u8_content(content):
    if "#EXTM3U" in content:
        return content
    try:
        decoded = content.replace("@", "1").replace("#", "2").replace("$", "3").replace("%", "4")
        raw = base64.b64decode(decoded).decode("utf-8", errors="ignore")
        return raw if "#EXTM3U" in raw else content
    except Exception:
        return content


def parse_m3u8(m3u8_content, base_url):
    lines = m3u8_content.strip().split("\n")
    result = {"ts_urls": [], "key_url": None, "key_iv": b"\x00" * 16,
              "is_master": False, "duration": 0, "best_url": None, "_best_h": 0}
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            result["is_master"] = True
            res = re.search(r"RESOLUTION=(\d+x(\d+))", line)
            if res and i + 1 < len(lines):
                vu = lines[i + 1].strip()
                if not vu.startswith("http"):
                    vu = urljoin(base_url, vu)
                h = int(res.group(2))
                if h > result["_best_h"]:
                    result["best_url"] = vu
                    result["_best_h"] = h
        elif line.startswith("#EXT-X-KEY"):
            uri_m = re.search(r'URI="([^"]*)"', line)
            if uri_m:
                ku = uri_m.group(1)
                result["key_url"] = ku if ku.startswith("http") else urljoin(base_url, ku)
            iv_m = re.search(r"IV=0x([0-9a-fA-F]+)", line)
            if iv_m:
                result["key_iv"] = bytes.fromhex(iv_m.group(1))
        elif line and not line.startswith("#"):
            result["ts_urls"].append(line if line.startswith("http") else urljoin(base_url, line))
        elif line.startswith("#EXTINF"):
            m = re.search(r"#EXTINF:([\d.]+)", line)
            if m:
                result["duration"] += float(m.group(1))
    return result


# ========== 下载器 ==========
class M3U8Downloader:
    def __init__(self, cookies_dict):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        for k, v in cookies_dict.items():
            self.session.cookies.set(k, v)

    def http_get(self, url, retries=3):
        for attempt in range(retries):
            try:
                resp = self.session.get(url, timeout=60)
                resp.raise_for_status()
                return resp
            except requests.RequestException:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def download_m3u8(self, url):
        resp = self.http_get(url)
        try:
            text = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            text = resp.content.decode("utf-8", errors="ignore")
        return decode_m3u8_content(text)

    def download_key(self, key_url):
        return self.http_get(key_url).content if key_url else None

    def download_ts(self, task):
        index, ts_url, key, iv, temp_dir = task
        ts_path = temp_dir / f"{index:06d}.ts"
        if ts_path.exists():
            return True
        try:
            resp = self.http_get(ts_url)
            data = resp.content
            if key:
                cipher = AES.new(key, AES.MODE_CBC, iv)
                data = cipher.decrypt(data)
                if data:
                    pad = data[-1]
                    if 0 < pad <= 16:
                        data = data[:-pad]
            ts_path.write_bytes(data)
            return True
        except Exception:
            return False

    def merge(self, temp_dir, output_path, ts_count):
        concat_file = temp_dir / "concat.txt"
        lines = []
        for i in range(ts_count):
            ts = temp_dir / f"{i:06d}.ts"
            if ts.exists():
                lines.append(f"file '{ts.as_posix()}'\n")
        if not lines:
            return False
        concat_file.write_text("".join(lines), encoding="utf-8")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        for bs_filter in [["-bsf:a", "aac_adtstoasc"], []]:
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                     "-i", str(concat_file), "-c", "copy"] + bs_filter + [str(output_path)],
                    check=True, capture_output=True, timeout=600,
                )
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
        return False

    def download_video(self, video_info, index, total):
        title = video_info.get("title", f"video_{index}")
        play_url = video_info.get("play_url", "")
        chapter = video_info.get("chapter_title", "")

        safe_title = sanitize_filename(title)
        safe_chapter = sanitize_filename(chapter) if chapter else ""
        prefix = f"{index:03d}_"
        mid = f"{safe_chapter}_{safe_title}" if safe_chapter else safe_title
        filename = prefix + mid + ".mp4"
        output_path = OUTPUT_DIR / filename

        if output_path.exists() and output_path.stat().st_size > 10 * 1024 * 1024:
            print(f"[{index}/{total}] SKIP {filename[:70]}")
            return True
        elif output_path.exists():
            print(f"[{index}/{total}] RE-DL {filename[:70]}")
            output_path.unlink()

        print(f"[{index}/{total}] DL {filename[:70]}")
        if not play_url:
            print(f"   NO_URL")
            return False

        temp_dir = OUTPUT_DIR / f".tmp_{index:03d}"
        temp_dir.mkdir(exist_ok=True)
        try:
            m3u8 = self.download_m3u8(play_url)
            parsed = parse_m3u8(m3u8, play_url)
            if parsed["is_master"] and parsed["best_url"]:
                m3u8 = self.download_m3u8(parsed["best_url"])
                parsed = parse_m3u8(m3u8, parsed["best_url"])

            if not parsed["ts_urls"]:
                print(f"   NO_TS")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return False

            n_ts = len(parsed["ts_urls"])
            print(f"   {n_ts}TS {parsed['duration']:.0f}s")

            key = None
            if parsed["key_url"]:
                try:
                    key = self.download_key(parsed["key_url"])
                except Exception:
                    pass

            tasks = [(i, u, key, parsed["key_iv"], temp_dir) for i, u in enumerate(parsed["ts_urls"])]
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
                list(ex.map(self.download_ts, tasks))

            if self.merge(temp_dir, output_path, n_ts):
                size_mb = output_path.stat().st_size / 1024 / 1024
                print(f"   OK {size_mb:.1f}MB")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return True
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        except Exception as e:
            print(f"   ERR {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

    def download_pdf(self, pdf_info, index, total):
        title = pdf_info.get("title", f"pdf_{index}")
        pdf_url = pdf_info.get("url", "")
        if not pdf_url:
            return False

        safe_title = sanitize_filename(title)
        output_path = OUTPUT_DIR / f"{index:03d}_{safe_title}"
        if output_path.exists() and output_path.stat().st_size > 1024:
            print(f"[{index}/{total}] SKIP PDF {safe_title[:60]}")
            return True

        print(f"[{index}/{total}] PDF {safe_title[:60]}")
        try:
            resp = self.http_get(pdf_url)
            output_path.write_bytes(resp.content)
            kb = len(resp.content) / 1024
            print(f"   OK {kb:.0f}KB")
            return True
        except Exception as e:
            print(f"   ERR {e}")
            return False


# ========== 主流程 ==========
async def main():
    print("=" * 60)
    print("小鹅通全自动视频批量下载器 v5")
    print("=" * 60)

    async with async_playwright() as p:
        print("[1/5] 启动浏览器...")
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        all_responses = []

        async def on_response(response):
            if "json" not in (response.headers.get("content-type", "")):
                return
            try:
                all_responses.append({
                    "url": response.url,
                    "method": response.request.method,
                    "post_data": response.request.post_data,
                    "body": await response.json(),
                })
            except Exception:
                pass

        page.on("response", on_response)

        # 登录
        print("[2/5] 打开课程页面...")
        await page.goto(COURSE_URL, wait_until="domcontentloaded", timeout=30000)
        print("\n" + "=" * 60)
        print(">>> 请在浏览器中登录 <<<")
        print("=" * 60)

        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url and "auth" not in page.url:
                await asyncio.sleep(3)
                if "login" not in page.url and "auth" not in page.url:
                    break
        else:
            print("超时")
            await browser.close()
            return

        print("登录成功!\n")

        # 提取课程资源
        all_responses.clear()
        print("[3/5] 提取所有课程资源...")
        try:
            await page.goto(COURSE_URL, wait_until="networkidle", timeout=30000)
        except Exception:
            await page.goto(COURSE_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        for i in range(60):
            try:
                await page.evaluate("window.scrollBy(0, 1200)")
            except Exception:
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(0.8)

        # 收集资源
        resources = {}
        for resp in all_responses:
            if "column.items.get" not in resp["url"]:
                continue
            body = resp.get("body", {})
            if not isinstance(body, dict):
                continue
            for item in body.get("data", {}).get("list", []):
                rid = item.get("resource_id") or item.get("id", "")
                if rid:
                    resources[rid] = {
                        "resource_id": rid,
                        "title": item.get("resource_title") or item.get("title") or item.get("resource_name", ""),
                        "chapter_title": item.get("chapter_title", ""),
                        "type": item.get("resource_type", 3),
                        "play_url": None,
                        "pdf_url": None,
                        "pdf_title": None,
                    }

        resource_list = list(resources.values())
        resource_list.sort(key=lambda x: x["resource_id"], reverse=True)
        print(f"   共 {len(resource_list)} 个资源")

        # 检测资源类型
        v_count = sum(1 for r in resource_list if r["resource_id"].startswith("v_"))
        l_count = sum(1 for r in resource_list if r["resource_id"].startswith("l_"))
        print(f"   视频(v_): {v_count}, 直播回放(l_): {l_count}")

        # 获取播放URL
        print(f"\n[4/5] 获取播放URL ({len(resource_list)} 个)...")

        if v_count > 0:
            print("   视频类型: 逐个打开视频页面触发getPlayUrl...")
            for i, v in enumerate(resource_list):
                if not v["resource_id"].startswith("v_"):
                    continue
                rid = v["resource_id"]
                try:
                    # 导航到视频页面
                    video_url = f"{BASE_URL}/p/course/video/{rid}?product_id={PRODUCT_ID}"
                    await page.goto(video_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(5)  # 等待播放器触发getPlayUrl

                    # 从最新捕获的响应中提取m3u8
                    for resp in reversed(all_responses):
                        if "getPlayUrl" in resp.get("url", ""):
                            body = resp.get("body", {})
                            data = body.get("data", {})
                            if isinstance(data, dict):
                                for key, val in data.items():
                                    if isinstance(val, dict):
                                        pl = val.get("play_list", {})
                                        for quality in ("720p_hls", "1080p_hls", "480p_hls"):
                                            if quality in pl and pl[quality].get("play_url"):
                                                v["play_url"] = pl[quality]["play_url"]
                                                break
                                        if v["play_url"]:
                                            break
                            if v["play_url"]:
                                break

                    # 从响应中提取PDF课件
                    for resp in reversed(all_responses):
                        if "courseware_list.get" in resp.get("url", ""):
                            body = resp.get("body", {})
                            c_list = body.get("data", [])
                            if isinstance(c_list, list) and c_list:
                                cw = c_list[0]
                                v["pdf_url"] = cw.get("url", "")
                                v["pdf_title"] = cw.get("title", "")
                            break
                    if (i + 1) % 5 == 0:
                        print(f"   进度: {i+1}/{len(resource_list)}")
                except Exception as e:
                    print(f"   [{i+1}] ERR: {e}")

        if l_count > 0:
            print("   直播回放类型: 调用get_lookback_list API...")
            for i, v in enumerate(resource_list):
                if not v["resource_id"].startswith("l_"):
                    continue
                try:
                    result = await page.evaluate("""
                        async ({base, app, rid}) => {
                            const r = await fetch(base + '/_alive/v3/get_lookback_list?app_id='
                                + app + '&alive_id=' + rid + '&protection=0', {credentials:'include'});
                            return await r.json();
                        }
                    """, {"base": BASE_URL, "app": APP_ID, "rid": v["resource_id"]})
                    data = result.get("data", [])
                    if isinstance(data, list) and data:
                        for line in data:
                            for s in line.get("line_sharpness", []):
                                if s.get("default") and s.get("url"):
                                    v["play_url"] = s["url"]
                                    break
                            if v["play_url"]:
                                break
                        if not v["play_url"] and data and data[0].get("line_sharpness"):
                            v["play_url"] = data[0]["line_sharpness"][0].get("url")
                except Exception:
                    pass

        has_url = sum(1 for v in resource_list if v["play_url"])
        print(f"   获取结果: {has_url}/{len(resource_list)}")

        # 保存
        export = {
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "course_url": COURSE_URL,
            "total": len(resource_list),
            "with_play_url": has_url,
            "videos": resource_list,
        }
        json_path = OUTPUT_DIR / "zhihu_videos.json"
        json_path.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")

        cookies = await context.cookies()
        cookies_dict = {c["name"]: c["value"] for c in cookies}
        await browser.close()
        print("[5/5] 浏览器已关闭\n")

    if has_url == 0:
        print("FAIL: 没有获取到播放URL")
        print(f"资源列表: {json_path}")
        sys.exit(1)

    print(f"开始下载 {len(resource_list)} 个视频 ({has_url} 有URL)...")
    print("=" * 60)

    downloader = M3U8Downloader(cookies_dict)
    success, failed = 0, 0

    for i, v in enumerate(resource_list, 1):
        if not v["play_url"]:
            continue
        try:
            if downloader.download_video(v, i, len(resource_list)):
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[{i}/{len(resource_list)}] EXC: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"DONE! success={success} failed={failed}")
    print(f"MP4: {len(list(OUTPUT_DIR.glob('*.mp4')))}")

    # 下载PDF课件
    pdfs = [v for v in resource_list if v.get("pdf_url")]
    if pdfs:
        print(f"\n下载 {len(pdfs)} 个PDF课件...")
        pdf_ok = 0
        for i, v in enumerate(pdfs, 1):
            try:
                if downloader.download_pdf({"title": v["pdf_title"], "url": v["pdf_url"]}, i, len(pdfs)):
                    pdf_ok += 1
            except Exception:
                pass
        print(f"PDF: {pdf_ok}/{len(pdfs)}")

    print(f"Dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())

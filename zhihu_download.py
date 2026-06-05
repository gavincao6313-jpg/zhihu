"""
知乎训练营课程视频下载器
======================
Playwright 打开页面 → 用户扫码登录 → 提取SSR数据 → 获取视频URL → 批量下载

用法: python zhihu_download.py
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from Crypto.Cipher import AES
import concurrent.futures
from playwright.async_api import async_playwright

# 配置
COURSE_URL = "https://www.zhihu.com/xen/market/training/training-video/1972723265349902377/1982458776650011941"
PRODUCT_ID = "1972723265349902377"
OUTPUT_DIR = Path(r"E:\AI产品经理课")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CONCURRENCY = 5


def sanitize_filename(name):
    name = name.replace("'", "").replace(" ", "_")
    for char in '<>:"/\\|?*':
        name = name.replace(char, "_")
    return name.strip("_.")[:200] or "untitled"


def parse_m3u8(m3u8_content, base_url):
    lines = m3u8_content.strip().split("\n")
    result = {"ts_urls": [], "key_url": None, "key_iv": b"\x00" * 16,
              "is_master": False, "best_url": None, "_best_h": 0}

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
    return result


class M3U8Downloader:
    def __init__(self, cookies_dict):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.zhihu.com/",
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
        safe_title = sanitize_filename(title)
        filename = f"{index:03d}_{safe_title}.mp4"
        output_path = OUTPUT_DIR / filename

        if output_path.exists() and output_path.stat().st_size > 10 * 1024 * 1024:
            print(f"[{index}/{total}] SKIP {filename[:70]}")
            return True
        elif output_path.exists():
            output_path.unlink()

        print(f"[{index}/{total}] DL {filename[:70]}")
        if not play_url:
            print(f"   NO_URL")
            return False

        temp_dir = OUTPUT_DIR / f".tmp_{index:03d}"
        temp_dir.mkdir(exist_ok=True)
        try:
            m3u8_text = self.http_get(play_url).content.decode("utf-8", errors="ignore")
            parsed = parse_m3u8(m3u8_text, play_url)
            if parsed["is_master"] and parsed["best_url"]:
                m3u8_text = self.http_get(parsed["best_url"]).content.decode("utf-8", errors="ignore")
                parsed = parse_m3u8(m3u8_text, parsed["best_url"])

            if not parsed["ts_urls"]:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return False

            n_ts = len(parsed["ts_urls"])
            print(f"   {n_ts}TS")

            key = self.http_get(parsed["key_url"]).content if parsed["key_url"] else None
            tasks = [(i, u, key, parsed["key_iv"], temp_dir) for i, u in enumerate(parsed["ts_urls"])]
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
                list(ex.map(self.download_ts, tasks))

            if self.merge(temp_dir, output_path, n_ts):
                print(f"   OK {output_path.stat().st_size/1024/1024:.0f}MB")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return True
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        except Exception as e:
            print(f"   ERR {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False


async def main():
    print("=" * 60)
    print("知乎训练营视频下载器")
    print("=" * 60)

    async with async_playwright() as p:
        # 使用本地 Chrome 配置（保留已有登录态）
        user_data_dir = r"C:\Users\Admin\AppData\Local\Google\Chrome\User Data"
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel=None,
            headless=False,
            args=["--start-maximized"],
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        all_responses = []
        async def on_resp(resp):
            if "json" in (resp.headers.get("content-type", "")):
                try:
                    all_responses.append({
                        "url": resp.url,
                        "body": await resp.json(),
                    })
                except:
                    pass
        page.on("response", on_resp)

        print("[1/4] 打开课程页面，请扫码登录...")
        await page.goto(COURSE_URL, wait_until="domcontentloaded", timeout=30000)

        # 等用户登录
        for _ in range(300):
            await asyncio.sleep(1)
            logged_in = await page.evaluate("() => !!document.cookie.includes('z_c0')")
            if logged_in:
                break
        else:
            print("登录超时")
            await context.close()
            return
        print("登录成功!\n")

        # 刷新页面获取 SSR 数据
        print("[2/4] 提取 SSR 数据...")
        await page.goto(COURSE_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        # 提取 appContext
        ssr_data = await page.evaluate("""
            () => {
                try {
                    const el = document.getElementById('js-initialData');
                    if (el) return JSON.parse(el.textContent);
                } catch(e) {}
                return window.appContext || null;
            }
        """)

        # 保存 SSR 数据
        with open(OUTPUT_DIR / "ssr_data.json", "w", encoding="utf-8") as f:
            json.dump(ssr_data, f, ensure_ascii=False, indent=2, default=str)
        print("   SSR数据已保存")

        # 提取视频列表
        videos = []
        if ssr_data:
            tv = ssr_data.get("__connectedAutoFetch", {}).get("trainingVideo", {}).get("data", {})
            chapters = tv.get("chapters", [])
            for ch in chapters:
                sections = ch.get("sections", [])
                for s in sections:
                    videos.append({
                        "section_id": str(s.get("id", "")),
                        "title": s.get("title", ""),
                        "chapter": ch.get("title", ""),
                        "resource_id": s.get("resource_id", ""),
                        "duration": s.get("duration", 0),
                        "play_url": None,
                    })

        if not videos:
            # 尝试从 API 获取
            print("   SSR无目录，尝试API...")
            resp = await page.evaluate("""
                async (pid) => {
                    const r = await fetch('/api/v4/market/training/product/' + pid + '/sections?limit=200', {credentials:'include'});
                    if (r.ok) return await r.json();
                    return null;
                }
            """, PRODUCT_ID)
            if resp:
                print(f"   API返回: {json.dumps(resp, ensure_ascii=False)[:500]}")

        print(f"   找到 {len(videos)} 个视频")
        if videos:
            for v in videos[:5]:
                print(f"      {v['title'][:50]} (resource: {v['resource_id'][:30]}...)")

        # 获取视频播放 URL
        print(f"\n[3/4] 获取播放URL...")

        for i, v in enumerate(videos):
            if not v["resource_id"]:
                continue
            rid = v["resource_id"]
            # 导航到视频页面触发播放 API
            section_url = f"https://www.zhihu.com/xen/market/training/training-video/{PRODUCT_ID}/{v['section_id']}"
            try:
                await page.goto(section_url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(5)

                # 从捕获的响应中找 m3u8
                for resp in reversed(all_responses):
                    body_str = json.dumps(resp.get("body", {}))
                    m3u8_match = re.search(r'(https?://[^"\s]*?\.m3u8[^"\s]*)', body_str)
                    if m3u8_match:
                        v["play_url"] = m3u8_match.group(1)
                        break

                if (i + 1) % 10 == 0:
                    print(f"   进度: {i+1}/{len(videos)}")
            except Exception as e:
                print(f"   [{i+1}] ERR: {e}")

        has_url = sum(1 for v in videos if v["play_url"])
        print(f"   获取结果: {has_url}/{len(videos)}")

        # 保存
        with open(OUTPUT_DIR / "zhihu_videos.json", "w", encoding="utf-8") as f:
            json.dump({"total": len(videos), "videos": videos}, f, ensure_ascii=False, indent=2)

        cookies = await context.cookies()
        cookies_dict = {c["name"]: c["value"] for c in cookies}
        await context.close()
        print("[4/4] 浏览器已关闭\n")

    if has_url == 0:
        print("FAIL: 没有获取到播放URL，SSR数据已保存待分析")
        print(f"目录: {OUTPUT_DIR}")
        sys.exit(1)

    downloader = M3U8Downloader(cookies_dict)
    success, failed = 0, 0
    for i, v in enumerate(videos, 1):
        if not v["play_url"]:
            continue
        if downloader.download_video(v, i, len(videos)):
            success += 1
        else:
            failed += 1

    print(f"\nDONE! success={success} failed={failed}")
    print(f"Dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())

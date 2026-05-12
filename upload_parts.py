#!/usr/bin/env python3
"""
批量上传 Videos/parts/ 下的 mp4 文件到 GitHub Release。
- 自动跳过已上传的文件（断点续传）
- 逐文件上传，失败自动重试 3 次
- 每 5% 打印一次进度

用法:
    export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
    python3 upload_parts.py

可选环境变量:
    GITHUB_OWNER   默认 gavincao6313-jpg
    GITHUB_REPO    默认 zhihu
    RELEASE_TAG    默认 zhihu-videos-AI
    PARTS_DIR      默认 Videos/parts
"""

import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

OWNER     = os.environ.get("GITHUB_OWNER", "gavincao6313-jpg")
REPO      = os.environ.get("GITHUB_REPO",  "zhihu")
TAG       = os.environ.get("RELEASE_TAG",  "zhihu-videos-AI")
PARTS_DIR = Path(__file__).parent / os.environ.get("PARTS_DIR", "Videos/parts")

API_BASE    = "https://api.github.com"
UPLOAD_BASE = "https://uploads.github.com"
MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_release(client: httpx.Client, token: str) -> dict:
    r = client.get(f"{API_BASE}/repos/{OWNER}/{REPO}/releases/tags/{TAG}", headers=_headers(token))
    r.raise_for_status()
    return r.json()


def list_uploaded_assets(client: httpx.Client, token: str, release_id: int) -> set[str]:
    uploaded, page = set(), 1
    while True:
        r = client.get(
            f"{API_BASE}/repos/{OWNER}/{REPO}/releases/{release_id}/assets",
            params={"per_page": 100, "page": page},
            headers=_headers(token),
        )
        r.raise_for_status()
        assets = r.json()
        if not assets:
            break
        for a in assets:
            uploaded.add(a["name"])
        page += 1
    return uploaded


def _progress_iter(path: Path, chunk_size: int = 512 * 1024):
    """生成器：逐块读取文件并打印进度，每 5% 一行。"""
    size = path.stat().st_size
    done = 0
    start = time.time()
    last_pct = -5
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            done += len(chunk)
            yield chunk
            pct = done / size * 100 if size else 0
            if pct - last_pct >= 5:
                elapsed = time.time() - start
                speed = done / elapsed / 1024 / 1024 if elapsed > 0 else 0
                print(f"  {pct:5.1f}%  {done/1024/1024:.0f}/{size/1024/1024:.0f} MB"
                      f"  {speed:.2f} MB/s", flush=True)
                last_pct = pct


def upload_asset(client: httpx.Client, token: str, release_id: int, part_path: Path) -> bool:
    url = (f"{UPLOAD_BASE}/repos/{OWNER}/{REPO}/releases/{release_id}/assets"
           f"?name={quote(part_path.name, safe='')}")
    headers = {**_headers(token), "Content-Type": "video/mp4"}

    size = part_path.stat().st_size
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt > 1:
                print(f"  第 {attempt} 次重试...")
            r = client.post(
                url,
                content=_progress_iter(part_path),
                headers={**headers, "Content-Length": str(size)},
            )
            if r.status_code == 422:
                print("  文件已存在（422），视为成功")
                return True
            r.raise_for_status()
            return True
        except Exception as e:
            print(f"  失败: {e}")
            if attempt < MAX_RETRIES:
                print(f"  {RETRY_DELAY}s 后重试...")
                time.sleep(RETRY_DELAY)

    return False


def main():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("错误：未设置 GITHUB_TOKEN")
        print("  export GITHUB_TOKEN=ghp_xxxxxxxxxxxx")
        sys.exit(1)

    parts = sorted(
        PARTS_DIR.glob("*_part*.mp4"),
        key=lambda p: (p.stem.rsplit("_part", 1)[0],
                       int(p.stem.rsplit("part", 1)[1]))
    )
    if not parts:
        print(f"在 {PARTS_DIR} 下没有找到 *_part*.mp4 文件")
        sys.exit(1)

    print(f"本地文件: {len(parts)} 个")
    print(f"目标 Release: {OWNER}/{REPO} @ {TAG}\n")

    with httpx.Client(timeout=httpx.Timeout(7200.0, connect=30.0)) as client:
        print("获取 Release 信息...")
        release    = get_release(client, token)
        release_id = release["id"]
        print(f"Release: [{release_id}] {release['name']}")

        print("拉取已上传文件列表...")
        uploaded = list_uploaded_assets(client, token, release_id)
        print(f"已上传: {len(uploaded)} 个\n")

        pending = [p for p in parts if p.name not in uploaded]
        print(f"待上传: {len(pending)} 个 / 共 {len(parts)} 个\n")
        if not pending:
            print("全部已上传，无需操作。")
            return

        success, failed = 0, []
        for i, part_path in enumerate(pending, 1):
            size_mb = part_path.stat().st_size / 1024 / 1024
            print(f"[{i}/{len(pending)}] {part_path.name}  ({size_mb:.0f} MB)")
            if upload_asset(client, token, release_id, part_path):
                success += 1
                print("  完成\n")
            else:
                failed.append(part_path.name)
                print("  跳过（达到最大重试次数）\n")

    print(f"全部完成。成功: {success}，失败: {len(failed)}")
    if failed:
        print("失败列表:")
        for f in failed:
            print(f"  {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()

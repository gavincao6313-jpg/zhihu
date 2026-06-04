"""
小鹅通相关资料批量下载器

前置：先用 scripts/xet_capture.js 在浏览器控制台采集链接，
      将 xetDump() 的输出保存为 scripts/links.json。

用法：
    python scripts/xet_download_pdfs.py
    python scripts/xet_download_pdfs.py --links scripts/links.json --out downloads/pdfs
    python scripts/xet_download_pdfs.py --dry-run       # 仅列出链接，不下载
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import requests

SCRIPT_DIR = Path(__file__).parent
DEFAULT_LINKS = SCRIPT_DIR / "links.json"
DEFAULT_OUT   = SCRIPT_DIR.parent / "downloads" / "xet_pdfs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://appzl5apwz41977.h5.xet.pomoho.com/",
}


def safe_filename(name: str) -> str:
    name = unquote(name)
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip()[:200]


def download_one(session: requests.Session, name: str, url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] 已存在 {dest.name}")
        return True
    try:
        r = session.get(url, headers=HEADERS, timeout=60, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
        size_kb = dest.stat().st_size // 1024
        print(f"  [ok]   {dest.name}  ({size_kb} KB)")
        return True
    except Exception as e:
        print(f"  [err]  {name}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def resolve_url(resource: dict) -> str | None:
    if resource.get("url"):
        return resource["url"]
    raw = resource.get("_raw") or {}
    for key in ("download_url", "file_url", "resource_url", "origin_url",
                "downloadUrl", "fileUrl", "url"):
        if raw.get(key):
            return raw[key]
    return None


def main():
    ap = argparse.ArgumentParser(description="小鹅通 PDF 批量下载")
    ap.add_argument("--links", default=str(DEFAULT_LINKS))
    ap.add_argument("--out",   default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true", help="仅列出链接，不下载")
    ap.add_argument("--delay", type=float, default=0.5, help="下载间隔秒数")
    args = ap.parse_args()

    links_path = Path(args.links)
    if not links_path.exists():
        print(f"[error] 找不到 {links_path}")
        print("请先在浏览器控制台运行 xet_capture.js，执行 xetDump()，")
        print(f"将输出的 JSON 保存为 {links_path}")
        sys.exit(1)

    data = json.loads(links_path.read_text(encoding="utf-8"))
    resources = data.get("resources", [])
    if not resources:
        print("[error] links.json 中 resources 为空")
        sys.exit(1)

    out_dir = Path(args.out)
    print(f"共 {len(resources)} 个文件 → {out_dir}")

    if args.dry_run:
        for i, r in enumerate(resources, 1):
            url = resolve_url(r)
            print(f"  {i:3}. {r.get('name', '?')}")
            print(f"       {url or '(无直接链接，需二次请求)'}")
        return

    session = requests.Session()
    ok = fail = 0

    for i, r in enumerate(resources, 1):
        name = safe_filename(r.get("name") or f"file_{r.get('id', i)}")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        dest = out_dir / name

        url = resolve_url(r)
        if not url:
            print(f"  [{i}/{len(resources)}] 无链接，跳过: {name}")
            fail += 1
            continue

        print(f"  [{i}/{len(resources)}] {name}")
        if download_one(session, name, url, dest):
            ok += 1
        else:
            fail += 1

        if i < len(resources):
            time.sleep(args.delay)

    print(f"\n完成：成功 {ok}，失败 {fail}")
    print(f"文件保存在：{out_dir.resolve()}")


if __name__ == "__main__":
    main()

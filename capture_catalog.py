"""通过知乎 API 获取完整课程目录
用法: python capture_catalog.py --course-id 1974142154118043353 [--out catalog.json]
"""
import argparse, json, sys
from pathlib import Path
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AUTH_FILE = Path("D:/zhihu/zhihu_auth_state.json")


def main():
    ap = argparse.ArgumentParser(description="知乎训练营课程目录抓取")
    ap.add_argument("--course-id", required=True, help="课程 ID")
    ap.add_argument("--out", default=None, help="输出 JSON 文件路径（默认 catalog_{course_id}.json）")
    ap.add_argument("--auth", default=str(AUTH_FILE), help="auth state JSON 路径")
    args = ap.parse_args()

    course_id = args.course_id
    out_file = Path(args.out) if args.out else Path(f"D:/zhihu/catalog_{course_id}.json")

    # 加载 cookies
    auth = json.loads(Path(args.auth).read_text("utf-8"))
    cookies = {c["name"]: c["value"] for c in auth["cookies"] if "zhihu.com" in c.get("domain", "")}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
        "Referer": f"https://www.zhihu.com/xen/market/training/training-video/{course_id}/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }

    all_sections = []
    offset = 0
    limit = 50

    while True:
        url = f"https://www.zhihu.com/api/education/training/{course_id}/video_page/catalog"
        r = requests.get(url, headers=headers, cookies=cookies, params={"limit": limit, "offset": offset}, timeout=30)
        if r.status_code != 200:
            print(f"HTTP {r.status_code}")
            break
        data = r.json()
        if data.get("errcode") != 0:
            print(f"API error: {data.get('errmsg', 'unknown')}")
            break
        catalog = data.get("data", [])
        if isinstance(catalog, dict):
            catalog = (catalog.get("list") or catalog.get("data") or catalog.get("sections") or catalog.get("chapters") or [])
        if not catalog:
            break
        for item in catalog:
            if isinstance(item, dict):
                sid = str(item.get("id") or item.get("section_id") or item.get("video_id") or "")
                title = item.get("title") or item.get("name") or ""
                if title and sid:
                    all_sections.append({"section_id": sid, "title": title})
        print(f"  offset={offset}: {len(catalog)} items, total={len(all_sections)}")
        if len(catalog) < limit:
            break
        offset += limit

    if not all_sections:
        print("FAIL: 未获取到目录数据")
        sys.exit(1)

    # 去重
    seen = set()
    unique = [v for v in all_sections if v["section_id"] not in seen and not seen.add(v["section_id"])]

    out_file.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n目录已保存: {out_file} ({len(unique)} 节)")
    for i, v in enumerate(unique, 1):
        print(f"  {i:2}. {v['title'][:80]}")


if __name__ == "__main__":
    main()

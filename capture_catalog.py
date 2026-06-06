"""通过知乎 API 获取完整课程目录"""
import json, sys, re
from pathlib import Path
import requests

AUTH_FILE = Path("D:/zhihu/zhihu_auth_state.json")
COURSE_ID = "1979243275383748550"
OUT_FILE = Path(f"D:/zhihu/catalog_{COURSE_ID}.json")

# 加载 cookies
auth = json.loads(AUTH_FILE.read_text("utf-8"))
cookies = {c["name"]: c["value"] for c in auth["cookies"] if "zhihu.com" in c.get("domain", "")}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
    "Referer": f"https://www.zhihu.com/xen/market/training/training-video/{COURSE_ID}/",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
}

# 翻页获取所有章节
all_sections = []
offset = 0
limit = 50

while True:
    url = f"https://www.zhihu.com/api/education/training/{COURSE_ID}/video_page/catalog"
    params = {"limit": limit, "offset": offset}
    r = requests.get(url, headers=headers, cookies=cookies, params=params, timeout=30)
    print(f"offset={offset}: status={r.status_code}, len={len(r.text)}")

    if r.status_code != 200:
        break

    data = r.json()
    if data.get("errcode") != 0:
        print(f"  API error: {data.get('errmsg', 'unknown')}")
        break

    catalog_data = data.get("data", [])
    if not catalog_data:
        break

    # catalog_data 可能是 list 或 dict
    if isinstance(catalog_data, dict):
        # 尝试从 dict 中提取列表
        catalog_data = (catalog_data.get("list") or catalog_data.get("data")
                       or catalog_data.get("sections") or catalog_data.get("chapters")
                       or catalog_data.get("items") or [])

    for item in catalog_data:
        if isinstance(item, dict):
            # 尝试提取 section_id 和 title
            sid = str(item.get("id") or item.get("section_id") or item.get("video_id") or "")
            title = item.get("title") or item.get("name") or item.get("display_title") or ""
            if title and sid:
                all_sections.append({"section_id": sid, "title": title})

    print(f"  本页 {len(catalog_data)} 条，累计 {len(all_sections)} 条")

    if len(catalog_data) < limit:
        break
    offset += limit

# 保存
if not all_sections:
    print("FAIL: 未获取到目录数据")
    print(f"Raw API response preview: {json.dumps(data, ensure_ascii=False, indent=2)[:2000]}")
    sys.exit(1)

# 去重
seen = set()
unique = []
for v in all_sections:
    if v["section_id"] not in seen:
        seen.add(v["section_id"])
        unique.append(v)

OUT_FILE.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n目录已保存: {OUT_FILE} ({len(unique)} 节)")
for i, v in enumerate(unique, 1):
    print(f"  {i:2}. {v['title'][:80]}")

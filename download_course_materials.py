"""下载知乎训练营课程"小结资料"PDF
用法: python download_course_materials.py --course-id 1972723265349902377 --out "E:\AI产品\AI产品经理培养计划"
"""
import argparse, json, re, sys, time, requests
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AUTH_FILE = Path("D:/zhihu/zhihu_auth_state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s)[:80]


def get_catalog_with_files(course_id, cookies, headers):
    """翻页获取完整目录，包含 file_list"""
    all_sections = []
    offset = 0
    limit = 50
    while True:
        url = f"https://www.zhihu.com/api/education/training/{course_id}/video_page/catalog"
        r = requests.get(url, headers=headers, cookies=cookies,
                        params={"limit": limit, "offset": offset}, timeout=30)
        if r.status_code != 200:
            break
        data = r.json()
        if data.get("errcode") != 0:
            break
        catalog = data.get("data", {}).get("data", [])
        if not catalog:
            break
        for item in catalog:
            sid = str(item.get("id", ""))
            title = item.get("title", "")
            file_list = item.get("file_list", [])
            all_sections.append({
                "section_id": sid,
                "title": title,
                "files": [{"name": f.get("file_name", ""), "size": f.get("file_size", 0),
                          "id": f.get("file_id", "")} for f in file_list],
            })
        print(f"  offset={offset}: {len(catalog)} sections, total={len(all_sections)}")
        if len(catalog) < limit:
            break
        offset += limit
    return all_sections


def resolve_download_url(file_id, cookies, headers):
    """调用 file API 获取真实下载 URL"""
    url = f"https://www.zhihu.com/api/education/file/{file_id}"
    r = requests.get(url, headers=headers, cookies=cookies, timeout=30)
    if r.status_code == 200:
        data = r.json()
        if data.get("errcode") == 0:
            return data.get("data", {}).get("file_url", "")
    return ""


def download_file(file_url, dest, headers):
    """下载文件到目标路径"""
    tmp = dest.with_suffix(".tmp.pdf")
    try:
        r = requests.get(file_url, headers={"User-Agent": UA}, timeout=600, stream=True)
        if r.status_code == 200:
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            size = tmp.stat().st_size
            if size > 1000 and b"%PDF" in tmp.read_bytes()[:10]:
                tmp.rename(dest)
                return True, size
            else:
                tmp.unlink()
                return False, 0
        return False, 0
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        return False, str(e)


def main():
    ap = argparse.ArgumentParser(description="知乎训练营课程小结资料PDF下载")
    ap.add_argument("--course-id", required=True, help="课程 ID")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--delay", type=float, default=1.0, help="下载间隔(秒)")
    args = ap.parse_args()

    course_id = args.course_id
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载 cookies
    auth = json.loads(AUTH_FILE.read_text("utf-8"))
    cookies = {c["name"]: c["value"] for c in auth["cookies"] if "zhihu.com" in c.get("domain", "")}
    headers = {
        "User-Agent": UA,
        "Referer": f"https://www.zhihu.com/xen/market/training/training-video/{course_id}/",
        "X-Requested-With": "XMLHttpRequest",
    }

    # Step 1: 获取目录（含 file_list）
    print("=== Step 1: 获取课程目录（含文件信息）===")
    sections = get_catalog_with_files(course_id, cookies, headers)
    sections_with_files = [s for s in sections if s["files"]]
    print(f"共 {len(sections)} 节，{len(sections_with_files)} 节有小结资料")

    if not sections_with_files:
        print("FAIL: 未找到任何小结资料")
        sys.exit(1)

    # Step 2: 解析下载URL并下载
    print("\n=== Step 2: 下载PDF文件 ===")
    ok = fail = skip = 0

    for i, section in enumerate(sections, 1):
        title = safe_name(section["title"])
        for j, f in enumerate(section["files"]):
            fname = safe_name(f["name"])
            if not fname.endswith(".pdf"):
                fname += ".pdf"

            # 编号：如果一节有多个文件，加字母后缀
            if len(section["files"]) > 1:
                dest = out_dir / f"{i:03d}{chr(97+j)}_{fname}"
            else:
                dest = out_dir / f"{i:03d}_{fname}"

            size_mb = f["size"] / 1048576 if f["size"] else 0
            print(f"\n[{i}/{len(sections)}] {title[:50]}")

            if dest.exists() and dest.stat().st_size > 10 * 1024:
                print(f"  SKIP {f['name']} (已存在)")
                skip += 1
                continue

            print(f"  文件: {f['name']} ({size_mb:.1f} MB)")
            print(f"  解析下载URL...")

            download_url = resolve_download_url(f["id"], cookies, headers)
            if not download_url:
                print(f"  FAIL: 无法获取下载URL")
                fail += 1
                continue

            print(f"  下载中...")
            success, result = download_file(download_url, dest, headers)
            if success:
                print(f"  OK {result/1048576:.1f} MB")
                ok += 1
            else:
                print(f"  FAIL: {result}")
                fail += 1

            time.sleep(args.delay)

    print(f"\n=== DONE ===")
    print(f"成功: {ok}  跳过: {skip}  失败: {fail}")
    print(f"保存位置: {out_dir.resolve()}")


if __name__ == "__main__":
    main()

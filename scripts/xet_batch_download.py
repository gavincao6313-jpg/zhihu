"""
小鹅通课程附件批量下载器（基于真实 API）

使用步骤：
  1. Chrome DevTools → Network → 点任意请求 → Headers → 复制 cookie 行的值
  2. 填入下方 COOKIE 变量，或用 --cookie 参数传入
  3. python scripts/xet_batch_download.py
  4. 文件保存到 downloads/xet_pdfs/
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import requests

# ── 配置区 ───────────────────────────────────────────────────────
BASE_URL   = "https://appzl5apwz41977.h5.xet.pomoho.com"
PRODUCT_ID = "p_62ee31c5e4b050af23a5b3e7"
COLUMN_ID  = "p_66f385aee4b0694c3c4b058c"

# 粘贴 Network 请求头里的完整 cookie 字符串（包含 ko_token）
COOKIE = "sensorsdata2015jssdkcross=%7B%22%24device_id%22%3A%2219e45335f94799-00c63681a241e98-17525631-1296000-19e45335f957e2%22%7D; xenbyfpfUnhLsdkZbX=0; sa_jssdk_2015_appzl5apwz41977_h5_xet_pomoho_com=%7B%22distinct_id%22%3A%22u_69ef23c048972_aM0D2u3Hlx%22%2C%22first_id%22%3A%2219e45335f94799-00c63681a241e98-17525631-1296000-19e45335f957e2%22%2C%22props%22%3A%7B%7D%7D; ko_token=8613f15eda68b8b31955058402ed6b08; newuserdays=90; olduserdays=180; regtime=1777279936; shop_version_type=4; colla_login=1; logintime=1780703548"

OUT_DIR = Path(__file__).parent.parent / "downloads" / "xet_pdfs"
# ────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": f"{BASE_URL}/p/course/column/{COLUMN_ID}?product_id={PRODUCT_ID}",
    "Origin": BASE_URL,
    "Accept": "application/json, text/plain, */*",
}


def api_post(session: requests.Session, path: str, data: dict) -> dict:
    r = session.post(f"{BASE_URL}/{path}", data=data, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def safe_filename(name: str) -> str:
    name = unquote(name)
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip()[:200]


def get_attach_list(session: requests.Session, known_path: str = "") -> list[dict]:
    # 从浏览器 Network 抓到的真实参数格式
    biz_params = {
        "bizData[resource_id]":      COLUMN_ID,
        "bizData[resource_type]":    "6",
        "bizData[check_available]":  "1",
    }
    # 加分页参数试探（原始请求只有 3 个字段，总数可能需要分页）
    biz_params_paged = {**biz_params, "page": 1, "page_size": 200}

    candidates = []
    if known_path:
        candidates.append((known_path, biz_params))
        candidates.append((known_path, biz_params_paged))

    candidates += [
        # 浏览器实际调用的接口 + 真实参数
        ("xe.course.business_go.courseware_list.get/2.0.0", biz_params),
        ("xe.course.business_go.courseware_list.get/2.0.0", biz_params_paged),
    ]

    for path, body in candidates:
        print(f"  探测 {path} ...", end=" ", flush=True)
        try:
            resp = api_post(session, path, body)
            code = resp.get("code") or resp.get("errcode") or resp.get("ret")
            if str(code) not in ("0", "200", "None"):
                print(f"code={code} 跳过")
                continue
            files = extract_files(resp)
            if files:
                print(f"找到 {len(files)} 个文件")
                return files
            # 保存调试响应
            slug = path.split("/")[0].replace(".", "_")
            dbg = Path(__file__).parent / f"debug_{slug}.json"
            dbg.write_text(json.dumps(resp, ensure_ascii=False, indent=2))
            print(f"无文件（已保存 {dbg.name} 供分析）")
        except Exception as e:
            print(f"失败: {e}")

    return []


def extract_files(data: object, depth: int = 0) -> list[dict]:
    if depth > 6 or not data:
        return []
    results = []
    if isinstance(data, list):
        for item in data:
            results.extend(extract_files(item, depth + 1))
        return results
    if not isinstance(data, dict):
        return []

    name = (data.get("name") or data.get("title") or data.get("file_name")
            or data.get("resource_name") or data.get("fileName") or "")
    fid  = (data.get("id") or data.get("file_id") or data.get("resource_id")
            or data.get("attach_id") or data.get("fileId") or "")
    url  = (data.get("url") or data.get("download_url") or data.get("file_url")
            or data.get("resource_url") or data.get("origin_url") or "")

    looks_like_file = bool(
        (name or fid)
        and (url or fid)
        and any(k in data for k in ("url", "file_url", "download_url", "resource_url",
                                    "origin_url", "file_id", "resource_id", "attach_id"))
    )
    if looks_like_file:
        results.append({"id": str(fid), "name": name, "url": url, "_raw": data})

    for key in ("list", "data", "items", "resources", "attachments",
                "files", "records", "attach", "courseware_list"):
        if data.get(key):
            results.extend(extract_files(data[key], depth + 1))
    return results


def get_download_url(session: requests.Session, file_id: str) -> str | None:
    for path in (
        "xe.upload.attach.download_url.get/2.0.0",
        "xe.course.business_go.attach_download.get/2.0.0",
        "xe.upload.resource.download_url.get/2.0.0",
    ):
        try:
            resp = api_post(session, path, {"file_id": file_id, "product_id": PRODUCT_ID})
            url = ((resp.get("data") or {}).get("url") or resp.get("url") or "")
            if url:
                return url
        except Exception:
            pass
    return None


def download_file(session: requests.Session, name: str, url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"    [skip] {dest.name}")
        return True
    try:
        r = session.get(url, headers={"User-Agent": HEADERS["User-Agent"]},
                        timeout=120, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                f.write(chunk)
        print(f"    [ok]   {dest.name}  ({dest.stat().st_size // 1024} KB)")
        return True
    except Exception as e:
        print(f"    [err]  {name}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def main():
    ap = argparse.ArgumentParser(description="小鹅通附件批量下载")
    ap.add_argument("--cookie", default="", help="浏览器完整 cookie 字符串")
    ap.add_argument("--api",    default="", help="已知的附件列表 API path，如 xe.xxx.get/2.0.0")
    ap.add_argument("--out",    default=str(OUT_DIR))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay",   type=float, default=0.5)
    args = ap.parse_args()

    cookie_str = args.cookie or COOKIE
    if "PASTE_COOKIE_HERE" in cookie_str:
        print("[error] 请填写 COOKIE 变量或用 --cookie 传入")
        print("  获取：DevTools → Network → 任意请求 → Headers → cookie 行")
        sys.exit(1)

    session = requests.Session()
    session.headers.update({"Cookie": cookie_str})

    print("探测附件列表接口...")
    files = get_attach_list(session, known_path=args.api)

    if not files:
        print("\n[提示] 未找到文件列表。")
        print("请在 Network 面板中点击「相关资料」按钮，")
        print("找到触发的那条 POST 请求，把 URL 路径部分（/xe.xxx.get/2.0.0）发给我。")
        sys.exit(1)

    print(f"\n共 {len(files)} 个文件 → {args.out}")

    if args.dry_run:
        for i, f in enumerate(files, 1):
            print(f"  {i:3}. {f['name']}  url={f['url'] or '(需换链)'}")
        return

    out_dir = Path(args.out)
    ok = fail = 0
    for i, f in enumerate(files, 1):
        name = safe_filename(f["name"] or f"file_{f['id']}_{i}")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        dest = out_dir / name

        url = f["url"]
        if not url and f["id"]:
            print(f"  [{i}/{len(files)}] 换链中...")
            url = get_download_url(session, f["id"])

        if not url:
            print(f"  [{i}/{len(files)}] 无链接: {name}")
            fail += 1
            continue

        print(f"  [{i}/{len(files)}] {name}")
        if download_file(session, name, url, dest):
            ok += 1
        else:
            fail += 1
        time.sleep(args.delay)

    print(f"\n完成: 成功 {ok}，失败 {fail}")
    print(f"路径: {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()

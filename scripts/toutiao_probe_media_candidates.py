from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from toutiao_common import (
    ANTI_DETECTION_ARGS,
    ANTI_DETECTION_INIT_SCRIPT,
    TOUTIAO_AUTH_STATE,
    TOUTIAO_PROBE_DIR,
    USER_AGENT,
    write_json,
)


MEDIA_HINT_RE = re.compile(
    r"https?://[^\"'\\\s<>]+(?:\.m3u8|\.mp4|\.flv|play|video|vod|tos-cn|ixigua|pstatp)[^\"'\\\s<>]*",
    re.IGNORECASE,
)
APP_GATE_TEXTS = (
    "打开App看完整内容",
    "下载西瓜视频",
    "打开西瓜视频",
    "App内打开",
)

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)


def load_queue(path: Path, limit: int, item_ids: set[str]) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if item_ids:
        items = [item for item in items if item.get("item_id") in item_ids]
    if limit:
        items = items[:limit]
    return items


def numeric_id(item_id: str) -> str:
    match = re.search(r"(\d{12,})", item_id or "")
    return match.group(1) if match else ""


def variant_urls(item: dict, names: list[str]) -> list[dict]:
    item_id = item.get("item_id", "")
    nid = numeric_id(item_id)
    original = item.get("detail_url", "")
    variants = {
        "original": original,
        "toutiao-group": f"https://www.toutiao.com/group/{nid}/" if nid else "",
        "toutiao-item": f"https://www.toutiao.com/item/{nid}/" if nid else "",
        "toutiao-mobile": f"https://m.toutiao.com/is/{nid}/" if nid else "",
        "ixigua-www": f"https://www.ixigua.com/{nid}/" if nid else "",
        "ixigua-mobile": f"https://m.ixigua.com/video/{nid}?wid_try=1" if nid else "",
    }
    selected = names or ["original", "toutiao-group", "ixigua-mobile"]
    seen = set()
    rows = []
    for name in selected:
        url = variants.get(name, "")
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append({"variant": name, "url": url})
    return rows


def compact_text(text: str, max_chars: int = 1200) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:max_chars]


def unique_limited(values: list[str], limit: int) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def relevant_url(url: str, item_number: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if item_number and item_number in url:
        return True
    return any(key in host for key in ("toutiao", "ixigua", "pstatp", "byteimg", "bytedance", "snssdk"))


async def probe_one_variant(browser, item: dict, variant: dict, args) -> dict:
    item_number = numeric_id(item.get("item_id", ""))
    context = await browser.new_context(
        viewport={"width": 390, "height": 844} if args.mobile else {"width": 1280, "height": 900},
        locale="zh-CN",
        user_agent=MOBILE_UA if args.mobile else USER_AGENT,
        storage_state=str(args.auth_state) if args.auth_state.exists() else None,
        is_mobile=args.mobile,
        has_touch=args.mobile,
    )
    await context.add_init_script(ANTI_DETECTION_INIT_SCRIPT)
    page = await context.new_page()

    requests: list[str] = []
    responses: list[dict] = []
    media_hints: list[str] = []

    def on_request(request):
        url = request.url
        if relevant_url(url, item_number):
            requests.append(url)
        if any(key in url.lower() for key in (".m3u8", ".mp4", ".flv", "play", "video", "vod")):
            media_hints.append(url)

    async def inspect_response(response):
        url = response.url
        if not relevant_url(url, item_number):
            return
        row = {
            "url": url,
            "status": response.status,
            "content_type": response.headers.get("content-type", ""),
        }
        responses.append(row)
        lowered = row["content_type"].lower()
        if not any(kind in lowered for kind in ("json", "text", "html", "javascript")):
            return
        try:
            body = await response.text()
        except Exception:
            return
        hints = MEDIA_HINT_RE.findall(body[: args.max_response_chars])
        if hints:
            media_hints.extend(hints)
            row["hint_count"] = len(hints)
        if any(text in body for text in APP_GATE_TEXTS):
            row["app_gate_text_found"] = True

    page.on("request", on_request)
    page.on("response", lambda response: asyncio.create_task(inspect_response(response)))

    result = {
        "variant": variant["variant"],
        "url": variant["url"],
        "final_url": "",
        "title": "",
        "status": "unknown",
        "body_excerpt": "",
        "app_gate_texts": [],
        "request_count": 0,
        "response_count": 0,
        "media_hints": [],
        "requests_sample": [],
        "responses_sample": [],
    }
    try:
        response = await page.goto(variant["url"], wait_until="domcontentloaded", timeout=args.timeout_ms)
        result["main_status"] = response.status if response else 0
        await page.wait_for_timeout(args.wait_ms)
        try:
            await page.mouse.wheel(0, 480)
            await page.wait_for_timeout(500)
            await page.mouse.click(190, 360)
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        body_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        result["status"] = "ok"
        result["final_url"] = page.url
        result["title"] = await page.title()
        result["body_excerpt"] = compact_text(body_text)
        result["app_gate_texts"] = [text for text in APP_GATE_TEXTS if text in body_text]
        if args.save_html:
            html_path = args.output_dir / f"media-probe-{item.get('item_id')}-{variant['variant']}.html"
            html_path.write_text(await page.content(), encoding="utf-8")
            result["html_path"] = str(html_path)
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
        try:
            result["final_url"] = page.url
        except Exception:
            pass
    finally:
        await page.wait_for_timeout(300)
        result["request_count"] = len(requests)
        result["response_count"] = len(responses)
        result["media_hints"] = unique_limited(media_hints, args.max_hints)
        result["requests_sample"] = unique_limited(requests, args.max_samples)
        result["responses_sample"] = responses[: args.max_samples]
        await context.close()
    return result


async def run_probe(items: list[dict], args) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed, args=ANTI_DETECTION_ARGS)
        try:
            rows = []
            variant_names = [name.strip() for name in args.variants.split(",") if name.strip()]
            for item in items:
                item_row = {
                    "item_id": item.get("item_id", ""),
                    "title": item.get("title", ""),
                    "duration_s": item.get("duration_s", 0),
                    "download_status": item.get("download_status", ""),
                    "variants": [],
                }
                for variant in variant_urls(item, variant_names):
                    item_row["variants"].append(await probe_one_variant(browser, item, variant, args))
                rows.append(item_row)
        finally:
            await browser.close()

    return {
        "schema_version": "toutiao-media-candidate-probe-v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "queue_json": str(args.queue_json),
        "headed": args.headed,
        "mobile": args.mobile,
        "items": rows,
    }


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# Toutiao Media Candidate Probe",
        "",
        f"- created_at: {report['created_at']}",
        f"- queue_json: {report['queue_json']}",
        f"- headed: {report['headed']}",
        f"- mobile: {report['mobile']}",
        "",
    ]
    for item in report["items"]:
        lines.extend(["", f"## {item['item_id']} {item.get('title', '')}", ""])
        for variant in item["variants"]:
            hints = variant.get("media_hints") or []
            lines.extend(
                [
                    f"### {variant['variant']}",
                    "",
                    f"- status: {variant.get('status')}",
                    f"- main_status: {variant.get('main_status', '')}",
                    f"- final_url: {variant.get('final_url', '')}",
                    f"- title: {variant.get('title', '')}",
                    f"- app_gate_texts: {', '.join(variant.get('app_gate_texts') or [])}",
                    f"- request_count: {variant.get('request_count', 0)}",
                    f"- response_count: {variant.get('response_count', 0)}",
                    f"- media_hints: {len(hints)}",
                ]
            )
            for hint in hints[:5]:
                lines.append(f"  - `{hint[:220]}`")
            excerpt = variant.get("body_excerpt") or ""
            if excerpt:
                lines.extend(["", f"> {excerpt[:500]}"])
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Toutiao/Xigua pages for hidden media candidates")
    parser.add_argument("--queue-json", type=Path, required=True)
    parser.add_argument("--auth-state", type=Path, default=TOUTIAO_AUTH_STATE)
    parser.add_argument("--output-dir", type=Path, default=TOUTIAO_PROBE_DIR)
    parser.add_argument("--label", default="")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--item-id", action="append", default=[])
    parser.add_argument("--variants", default="original,toutiao-group,ixigua-mobile")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--mobile", action="store_true")
    parser.add_argument("--save-html", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--wait-ms", type=int, default=6000)
    parser.add_argument("--max-response-chars", type=int, default=500000)
    parser.add_argument("--max-hints", type=int, default=20)
    parser.add_argument("--max-samples", type=int, default=40)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    items = load_queue(args.queue_json, args.limit, set(args.item_id))
    report = asyncio.run(run_probe(items, args))
    label = args.label or datetime.now().strftime("%Y%m%dT%H%M%S")
    json_path = args.output_dir / f"media-candidate-probe-{label}.json"
    md_path = args.output_dir / f"media-candidate-probe-{label}.md"
    write_json(json_path, report)
    write_markdown(report, md_path)
    print(f"Media candidate probe JSON: {json_path}")
    print(f"Media candidate probe MD  : {md_path}")
    for item in report["items"]:
        hint_count = sum(len(variant.get("media_hints") or []) for variant in item["variants"])
        app_gate_count = sum(1 for variant in item["variants"] if variant.get("app_gate_texts"))
        print(f"- {item['item_id']}: hints={hint_count} app_gate_variants={app_gate_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

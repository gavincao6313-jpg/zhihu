from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from toutiao_common import (
    ANTI_DETECTION_ARGS,
    DEFAULT_FAVORITES_URL,
    TOUTIAO_AUTH_STATE,
    TOUTIAO_MANIFEST,
    TOUTIAO_PROBE_DIR,
    build_playwright_context,
    canonical_url,
    ensure_dirs,
    extract_item_id,
    load_manifest,
    normalize_title,
    now_iso,
    save_manifest,
    sha1_short,
    write_json,
)


CONTENT_TYPES = ("video", "article", "image", "audio", "text", "mixed", "unknown")


def collect_card_candidates(page, favorites_url: str) -> list[dict]:
    raw_cards = page.evaluate(
        """
        () => {
          function compact(text) {
            return String(text || '').replace(/\\s+/g, ' ').trim();
          }
          function ancestorSummary(anchor) {
            let node = anchor;
            let best = anchor;
            for (let i = 0; i < 5 && node; i += 1) {
              const text = compact(node.innerText || node.textContent || '');
              if (text.length > compact(best.innerText || best.textContent || '').length) {
                best = node;
              }
              node = node.parentElement;
            }
            const imgs = Array.from(best.querySelectorAll('img')).map((img) => ({
              src: img.currentSrc || img.src || '',
              alt: compact(img.alt || img.getAttribute('aria-label') || ''),
            })).filter((img) => img.src || img.alt).slice(0, 12);
            return {
              text: compact(best.innerText || best.textContent || ''),
              className: String(best.className || ''),
              image_count: imgs.length,
              images: imgs,
              has_video_tag: Boolean(best.querySelector('video')),
              has_audio_tag: Boolean(best.querySelector('audio')),
            };
          }
          return Array.from(document.querySelectorAll('a[href]')).map((a) => {
            const summary = ancestorSummary(a);
            return {
              href: a.href || a.getAttribute('href') || '',
              anchor_text: compact(a.innerText || a.textContent || ''),
              title: compact(a.getAttribute('title') || ''),
              aria: compact(a.getAttribute('aria-label') || ''),
              card_text: summary.text,
              card_class: summary.className,
              image_count: summary.image_count,
              images: summary.images,
              has_video_tag: summary.has_video_tag,
              has_audio_tag: summary.has_audio_tag,
            };
          });
        }
        """
    )

    cards: dict[str, dict] = {}
    for raw in raw_cards:
        url = canonical_url(raw.get("href") or "", favorites_url)
        if not is_probable_toutiao_item_url(url):
            continue
        item_id = extract_item_id(url)
        existing = cards.get(item_id)
        card_text = normalize_space(raw.get("card_text") or "")
        title = normalize_title(
            raw.get("title") or raw.get("anchor_text") or raw.get("aria") or first_text_line(card_text),
            item_id,
        )
        candidate = {
            "item_id": item_id,
            "title": title,
            "detail_url": url,
            "anchor_text": normalize_space(raw.get("anchor_text") or ""),
            "card_text": card_text[:1200],
            "card_text_chars": len(card_text),
            "image_count": int(raw.get("image_count") or 0),
            "images": raw.get("images") or [],
            "has_video_tag": bool(raw.get("has_video_tag")),
            "has_audio_tag": bool(raw.get("has_audio_tag")),
            "signals": [],
        }
        if existing is None or score_candidate(candidate) > score_candidate(existing):
            cards[item_id] = candidate
    return list(cards.values())


def is_probable_toutiao_item_url(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if not any(domain in host for domain in ("toutiao.com", "ixigua.com")):
        return False
    if any(skip in path for skip in ("/c/user/", "/search/", "/question/", "/wenda/")):
        return False
    if path in ("", "/"):
        return False
    return bool(
        re.search(r"/(video|group|article|item|image|audio)/", path)
        or re.search(r"\d{12,}", path)
        or "ixigua.com" in host
    )


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def first_text_line(text: str) -> str:
    for part in re.split(r"[。！？.!?]| {2,}", text):
        part = normalize_space(part)
        if len(part) >= 4:
            return part[:120]
    return ""


def score_candidate(card: dict) -> int:
    return (
        len(card.get("title") or "")
        + min(card.get("card_text_chars") or 0, 1000)
        + int(card.get("image_count") or 0) * 20
        + (50 if card.get("has_video_tag") else 0)
        + (50 if card.get("has_audio_tag") else 0)
    )


def classify_card(card: dict, network_urls: list[str]) -> dict:
    text = normalize_space(" ".join([card.get("title") or "", card.get("card_text") or ""]))
    url = (card.get("detail_url") or "").lower()
    host = urlparse(url).netloc.lower()
    signals: list[str] = []

    if card.get("has_audio_tag") or keyword_hit(text, ("音频", "语音", "播客", "收听", "听书")):
        signals.append("audio_dom_or_keyword")
    if any(token in u.lower() for u in network_urls for token in (".mp3", ".m4a", ".aac", "/audio/")):
        signals.append("audio_network_seen")
    if card.get("has_video_tag") or "/video/" in url or "ixigua.com" in host:
        signals.append("video_url_or_dom")
    if keyword_hit(text, ("视频", "播放", "西瓜视频")):
        signals.append("video_keyword")
    if "/article/" in url or keyword_hit(text, ("阅读全文", "文章", "发布于", "头条号")):
        signals.append("article_url_or_keyword")
    if "/image/" in url or keyword_hit(text, ("图集", "图片", "相册")):
        signals.append("image_url_or_keyword")
    if int(card.get("image_count") or 0) >= 3:
        signals.append("multiple_images")
    if int(card.get("card_text_chars") or 0) >= 240:
        signals.append("long_card_text")

    content_type = "unknown"
    confidence = "low"
    if any(s.startswith("audio") for s in signals):
        content_type = "audio"
        confidence = "medium"
    elif "video_url_or_dom" in signals:
        content_type = "video"
        confidence = "high"
    elif "video_keyword" in signals and not ("article_url_or_keyword" in signals):
        content_type = "video"
        confidence = "medium"
    elif "image_url_or_keyword" in signals or (
        "multiple_images" in signals and "long_card_text" not in signals
    ):
        content_type = "image"
        confidence = "medium"
    elif "article_url_or_keyword" in signals or "long_card_text" in signals:
        content_type = "article"
        confidence = "medium" if "long_card_text" in signals else "low"
    elif 20 <= int(card.get("card_text_chars") or 0) < 240:
        content_type = "text"
        confidence = "low"

    if content_type in ("article", "image") and "video_keyword" in signals:
        content_type = "mixed"
        confidence = "low"

    result = dict(card)
    result["content_type"] = content_type
    result["classification_confidence"] = confidence
    result["signals"] = signals
    return result


def load_json_favorites_payload(body_text: str) -> dict | None:
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    return payload


def parse_json_favorites(body_text: str, favorites_url: str) -> list[dict]:
    payload = load_json_favorites_payload(body_text)
    if payload is None:
        return []
    return parse_json_payload_items(payload, favorites_url)


def parse_json_payload_items(payload: dict, favorites_url: str) -> list[dict]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    cards: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        detail_url = canonical_url(
            str(
                row.get("display_url")
                or row.get("source_url")
                or row.get("article_url")
                or row.get("media_url")
                or ""
            ),
            favorites_url,
        )
        stable_id = str(row.get("group_id") or row.get("item_id") or row.get("id") or "")
        item_id = f"toutiao-{stable_id}" if stable_id else extract_item_id(detail_url)
        images = []
        for image in row.get("image_list") or []:
            if isinstance(image, dict):
                src = image.get("url") or image.get("uri") or ""
                if src:
                    images.append({"src": canonical_image_url(src), "alt": ""})
        image_url = str(row.get("image_url") or "")
        if image_url:
            images.insert(0, {"src": canonical_image_url(image_url), "alt": ""})
        title = normalize_title(str(row.get("title") or ""), item_id)
        abstract = normalize_space(str(row.get("abstract") or ""))
        card = {
            "item_id": item_id,
            "title": title,
            "detail_url": detail_url,
            "anchor_text": title,
            "card_text": abstract[:1200],
            "card_text_chars": len(abstract),
            "image_count": max(int(row.get("gallary_image_count") or 0), len(images)),
            "images": images[:12],
            "has_video_tag": bool(row.get("has_video"))
            or str(row.get("article_genre") or "").lower() == "video",
            "has_audio_tag": False,
            "signals": ["json_api_row"],
            "raw_json_fields": {
                "chinese_tag": row.get("chinese_tag", ""),
                "tag_url": row.get("tag_url", ""),
                "article_genre": row.get("article_genre", ""),
                "source": row.get("source", ""),
                "video_duration_str": row.get("video_duration_str", ""),
                "comments_count": row.get("comments_count", ""),
                "go_detail_count": row.get("go_detail_count", ""),
                "repin_time": row.get("repin_time", ""),
            },
        }
        classified = classify_json_card(card, row)
        cards.append(classified)
    return cards


def next_favorites_page_url(favorites_url: str, payload: dict) -> str:
    cursor = payload.get("max_repin_time")
    if not cursor:
        return ""
    joiner = "&" if "?" in favorites_url else "?"
    return f"{favorites_url}{joiner}max_repin_time={cursor}"


def canonical_image_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.toutiao.com" + url
    return url


def classify_json_card(card: dict, row: dict) -> dict:
    tag_text = normalize_space(
        " ".join(
            str(row.get(key) or "")
            for key in ("chinese_tag", "tag_url", "article_genre", "title", "abstract")
        )
    )
    signals = list(card.get("signals") or [])
    article_genre = str(row.get("article_genre") or "").lower()
    tag_url = str(row.get("tag_url") or "").lower()
    chinese_tag = str(row.get("chinese_tag") or "")
    has_video = bool(row.get("has_video")) or article_genre == "video" or tag_url == "video"
    has_gallery = bool(row.get("has_gallery")) or int(row.get("gallary_image_count") or 0) > 0

    content_type = "unknown"
    confidence = "low"
    if has_video or "视频" in chinese_tag:
        content_type = "video"
        confidence = "high"
        signals.append("json_video_fields")
    elif "audio" in article_genre or "音频" in tag_text or "语音" in tag_text:
        content_type = "audio"
        confidence = "medium"
        signals.append("json_audio_fields")
    elif has_gallery or "图集" in chinese_tag or "image" in article_genre:
        content_type = "image"
        confidence = "medium"
        signals.append("json_gallery_fields")
    elif article_genre or row.get("title") or row.get("abstract"):
        content_type = "article"
        confidence = "medium"
        signals.append("json_text_fields")

    result = dict(card)
    result["content_type"] = content_type
    result["classification_confidence"] = confidence
    result["signals"] = signals
    return result


def keyword_hit(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def summarize_network(urls: list[str]) -> dict:
    counts = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    for url in sorted(set(urls)):
        lowered = url.lower()
        kind = "other"
        if any(token in lowered for token in (".mp4", ".m3u8", ".flv", "/video/")):
            kind = "video"
        elif any(token in lowered for token in (".mp3", ".m4a", ".aac", "/audio/")):
            kind = "audio"
        elif any(token in lowered for token in (".jpg", ".jpeg", ".png", ".webp", "/image/")):
            kind = "image"
        elif any(token in lowered for token in ("/article/", "/group/", "/item/")):
            kind = "article_or_item"
        counts[kind] += 1
        if len(samples[kind]) < 12:
            samples[kind].append(url)
    return {"counts": dict(counts), "samples": dict(samples)}


def update_manifest_with_classifications(items: list[dict], manifest_path: Path) -> dict:
    manifest = load_manifest(manifest_path)
    manifest["schema_version"] = "toutiao-favorites-manifest-v2"
    records = manifest.setdefault("items", {})
    now = now_iso()
    new_count = 0
    updated_count = 0
    for item in items:
        item_id = item["item_id"]
        record = records.get(item_id)
        if record is None:
            record = {
                "item_id": item_id,
                "first_seen_at": now,
                "download_status": "pending",
                "local_path": "",
                "downloaded_at": "",
                "download_method": "",
                "last_error": "",
            }
            records[item_id] = record
            new_count += 1
        else:
            updated_count += 1
        record.update(
            {
                "title": item.get("title") or item_id,
                "detail_url": item.get("detail_url") or "",
                "source": "favorites",
                "author": record.get("author", ""),
                "cover_url": first_image(item),
                "last_seen_at": now,
                "content_type": item.get("content_type", "unknown"),
                "classification_confidence": item.get("classification_confidence", "low"),
                "classification_signals": item.get("signals", []),
                "card_text_excerpt": (item.get("card_text") or "")[:500],
                "raw_status": record.get("raw_status", "pending"),
                "preprocess_status": record.get("preprocess_status", "pending"),
                "card_status": record.get("card_status", "pending"),
                "synthesis_status": record.get("synthesis_status", "pending"),
            }
        )
    manifest["last_classification"] = {
        "at": now,
        "seen": len(items),
        "new": new_count,
        "updated": updated_count,
        "counts": dict(Counter(item.get("content_type", "unknown") for item in items)),
    }
    save_manifest(manifest, manifest_path)
    return manifest


def first_image(item: dict) -> str:
    for image in item.get("images") or []:
        src = image.get("src") or ""
        if src:
            return src
    return ""


def write_markdown_report(report: dict, path: Path) -> None:
    counts = report["summary"]["content_type_counts"]
    lines = [
        "# Toutiao Favorites Classification Report",
        "",
        f"- created_at: {report['created_at']}",
        f"- favorites_url: {report['favorites_url']}",
        f"- current_url: {report['current_url']}",
        f"- page_title: {report['page_title']}",
        f"- items: {report['summary']['item_count']}",
        f"- pages_fetched: {report['summary'].get('pages_fetched', 0)}",
        "",
        "## Counts",
        "",
        "| content_type | count |",
        "|---|---:|",
    ]
    for content_type in CONTENT_TYPES:
        lines.append(f"| {content_type} | {counts.get(content_type, 0)} |")
    lines.extend(["", "## Items", "", "| type | confidence | title | url |", "|---|---|---|---|"])
    for item in report["items"]:
        title = (item.get("title") or item["item_id"]).replace("|", "\\|")
        url = item.get("detail_url") or ""
        lines.append(
            f"| {item.get('content_type')} | {item.get('classification_confidence')} | {title[:80]} | {url} |"
        )
    lines.extend(["", "## Unknown Or Low Confidence", ""])
    unsure = [
        item
        for item in report["items"]
        if item.get("content_type") == "unknown" or item.get("classification_confidence") == "low"
    ]
    if not unsure:
        lines.append("None.")
    for item in unsure:
        lines.extend(
            [
                f"### {item.get('title') or item['item_id']}",
                "",
                f"- item_id: {item['item_id']}",
                f"- type: {item.get('content_type')}",
                f"- url: {item.get('detail_url')}",
                f"- signals: {', '.join(item.get('signals') or []) or 'none'}",
                f"- text: {(item.get('card_text') or '')[:240]}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def probe_and_classify(args: argparse.Namespace) -> dict:
    ensure_dirs()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright 未安装。请先安装依赖：python3 -m pip install playwright && python3 -m playwright install chromium"
        ) from exc

    if not args.auth_state.exists() and not args.allow_no_auth_state:
        raise FileNotFoundError(
            f"未找到登录态 {args.auth_state}。先运行 scripts/toutiao_login.py，"
            "或本脚本加 --allow-no-auth-state 做未登录页面探测。"
        )

    network_candidates: list[str] = []
    console_messages: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, args=ANTI_DETECTION_ARGS)
        context = build_playwright_context(browser, args.auth_state if args.auth_state.exists() else None)
        page = context.new_page()

        def on_request(request) -> None:
            url = request.url
            lowered = url.lower()
            if any(
                token in lowered
                for token in (
                    "toutiao",
                    "ixigua",
                    ".mp4",
                    ".m3u8",
                    ".mp3",
                    ".m4a",
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".webp",
                    "/video/",
                    "/article/",
                    "/audio/",
                    "/image/",
                    "/group/",
                    "/item/",
                )
            ):
                network_candidates.append(url)

        page.on("request", on_request)
        page.on("console", lambda msg: console_messages.append(f"{msg.type}: {msg.text[:300]}"))
        page.goto(args.favorites_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        page.wait_for_timeout(args.wait_ms)
        for _ in range(args.scrolls):
            page.mouse.wheel(0, args.scroll_px)
            page.wait_for_timeout(args.scroll_wait_ms)

        title = page.title()
        current_url = page.url
        body_text = page.locator("body").inner_text(timeout=5000)
        body_excerpt = body_text[:3000]
        first_payload = load_json_favorites_payload(body_text)
        json_items = parse_json_payload_items(first_payload, args.favorites_url) if first_payload else []
        pages_fetched = 1 if first_payload else 0
        page_urls = [current_url] if first_payload else []
        seen_page_cursors = {first_payload.get("max_repin_time")} if first_payload else set()
        payload = first_payload
        while (
            payload
            and payload.get("has_more")
            and payload.get("max_repin_time")
            and pages_fetched < args.max_pages
        ):
            next_url = next_favorites_page_url(args.favorites_url, payload)
            next_cursor = payload.get("max_repin_time")
            if not next_url or next_cursor in seen_page_cursors and pages_fetched > 1:
                break
            seen_page_cursors.add(next_cursor)
            page.goto(next_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            page.wait_for_timeout(args.page_wait_ms)
            next_body = page.locator("body").inner_text(timeout=5000)
            payload = load_json_favorites_payload(next_body)
            if not payload:
                break
            pages_fetched += 1
            page_urls.append(page.url)
            json_items.extend(parse_json_payload_items(payload, args.favorites_url))

        if json_items:
            deduped_json_items: dict[str, dict] = {}
            for item in json_items:
                deduped_json_items[item["item_id"]] = item
            json_items = list(deduped_json_items.values())

        cards = json_items or collect_card_candidates(page, args.favorites_url)
        if args.limit:
            cards = cards[: args.limit]
        classified = cards if json_items else [classify_card(card, network_candidates) for card in cards]

        screenshot_path = ""
        if args.screenshot:
            screenshot = TOUTIAO_PROBE_DIR / f"classify-{args.probe_ts}.png"
            page.screenshot(path=str(screenshot), full_page=True)
            screenshot_path = str(screenshot)
        browser.close()

    counts = Counter(item.get("content_type", "unknown") for item in classified)
    report = {
        "schema_version": "toutiao-favorites-classification-v1",
        "created_at": now_iso(),
        "favorites_url": args.favorites_url,
        "current_url": current_url,
        "page_title": title,
        "body_excerpt": body_excerpt,
        "auth_state": str(args.auth_state),
        "screenshot_path": screenshot_path,
        "summary": {
            "item_count": len(classified),
            "content_type_counts": dict(counts),
            "confidence_counts": dict(
                Counter(item.get("classification_confidence", "low") for item in classified)
            ),
            "network": summarize_network(network_candidates),
            "pages_fetched": pages_fetched,
            "page_urls": page_urls,
        },
        "items": classified,
        "network_candidates": sorted(set(network_candidates))[:300],
        "console_messages": console_messages[-80:],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Toutiao favorites into knowledge-ingest content types")
    parser.add_argument("--favorites-url", default=DEFAULT_FAVORITES_URL)
    parser.add_argument("--auth-state", type=Path, default=TOUTIAO_AUTH_STATE)
    parser.add_argument("--manifest", type=Path, default=TOUTIAO_MANIFEST)
    parser.add_argument("--probe-ts", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--scrolls", type=int, default=10)
    parser.add_argument("--scroll-px", type=int, default=1600)
    parser.add_argument("--scroll-wait-ms", type=int, default=1000)
    parser.add_argument("--wait-ms", type=int, default=3000)
    parser.add_argument("--page-wait-ms", type=int, default=500)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument("--update-manifest", action="store_true")
    parser.add_argument("--allow-no-auth-state", action="store_true")
    args = parser.parse_args()
    args.probe_ts = args.probe_ts or now_iso().replace(":", "").replace("-", "")

    report = probe_and_classify(args)
    json_path = TOUTIAO_PROBE_DIR / f"classify-{args.probe_ts}.json"
    md_path = TOUTIAO_PROBE_DIR / f"classify-{args.probe_ts}.md"
    write_json(json_path, report)
    write_markdown_report(report, md_path)

    print(f"Classification JSON: {json_path}")
    print(f"Classification MD  : {md_path}")
    print(f"Items found        : {report['summary']['item_count']}")
    print(f"Counts             : {report['summary']['content_type_counts']}")
    print(f"Confidence         : {report['summary']['confidence_counts']}")
    print(f"Page title         : {report['page_title']}")
    print(f"Current URL        : {report['current_url']}")

    if args.update_manifest:
        manifest = update_manifest_with_classifications(report["items"], args.manifest)
        print(f"Manifest           : {args.manifest} ({len(manifest.get('items', {}))} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from pathlib import Path

from toutiao_common import (
    ANTI_DETECTION_ARGS,
    DEFAULT_FAVORITES_URL,
    TOUTIAO_AUTH_STATE,
    TOUTIAO_MANIFEST,
    TOUTIAO_PROBE_DIR,
    ToutiaoItem,
    build_playwright_context,
    canonical_url,
    ensure_dirs,
    extract_item_id,
    load_manifest,
    looks_like_video_url,
    merge_items_into_manifest,
    normalize_title,
    now_iso,
    write_json,
)


def collect_anchor_candidates(page, favorites_url: str) -> list[ToutiaoItem]:
    anchors = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).map((a) => ({
          href: a.href || a.getAttribute('href') || '',
          text: (a.innerText || a.textContent || '').trim(),
          title: a.getAttribute('title') || '',
          aria: a.getAttribute('aria-label') || ''
        }))
        """
    )
    items: dict[str, ToutiaoItem] = {}
    for anchor in anchors:
        url = canonical_url(anchor.get("href") or "", favorites_url)
        if not looks_like_video_url(url):
            continue
        item_id = extract_item_id(url)
        title = normalize_title(
            anchor.get("title") or anchor.get("text") or anchor.get("aria") or "",
            item_id,
        )
        items[item_id] = ToutiaoItem(item_id=item_id, title=title, detail_url=url)
    return list(items.values())


def probe_favorites(args: argparse.Namespace) -> dict:
    ensure_dirs()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright 未安装。请先 pip install playwright && playwright install chromium") from exc

    network_candidates: list[str] = []
    console_messages: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, args=ANTI_DETECTION_ARGS)
        context = build_playwright_context(browser, args.auth_state)
        page = context.new_page()

        def on_request(request) -> None:
            url = request.url
            lowered = url.lower()
            if any(token in lowered for token in ("/video/", "/group/", ".mp4", ".m3u8", "ixigua")):
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
        body_text = page.locator("body").inner_text(timeout=5000)[:2000]
        items = collect_anchor_candidates(page, args.favorites_url)
        if args.limit:
            items = items[:args.limit]

        screenshot_path = ""
        if args.screenshot:
            screenshot = TOUTIAO_PROBE_DIR / f"favorites-{args.probe_ts}.png"
            page.screenshot(path=str(screenshot), full_page=True)
            screenshot_path = str(screenshot)
        browser.close()

    probe = {
        "schema_version": "toutiao-favorites-probe-v1",
        "created_at": now_iso(),
        "favorites_url": args.favorites_url,
        "current_url": current_url,
        "page_title": title,
        "body_excerpt": body_text,
        "item_count": len(items),
        "items": [item.__dict__ for item in items],
        "network_candidates": sorted(set(network_candidates))[:200],
        "console_messages": console_messages[-50:],
        "screenshot_path": screenshot_path,
        "auth_state": str(args.auth_state),
    }
    return probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Toutiao favorites with logged-in Playwright state")
    parser.add_argument("--favorites-url", default=DEFAULT_FAVORITES_URL)
    parser.add_argument("--auth-state", type=Path, default=TOUTIAO_AUTH_STATE)
    parser.add_argument("--manifest", type=Path, default=TOUTIAO_MANIFEST)
    parser.add_argument("--probe-ts", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--scrolls", type=int, default=8)
    parser.add_argument("--scroll-px", type=int, default=1600)
    parser.add_argument("--scroll-wait-ms", type=int, default=1000)
    parser.add_argument("--wait-ms", type=int, default=3000)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument("--update-manifest", action="store_true")
    args = parser.parse_args()
    args.probe_ts = args.probe_ts or now_iso().replace(":", "").replace("-", "")

    probe = probe_favorites(args)
    probe_path = TOUTIAO_PROBE_DIR / f"favorites-{args.probe_ts}.json"
    write_json(probe_path, probe)
    print(f"Probe written: {probe_path}")
    print(f"Items found  : {probe['item_count']}")
    print(f"Page title   : {probe['page_title']}")
    print(f"Current URL  : {probe['current_url']}")

    if args.update_manifest:
        items = [ToutiaoItem(**raw) for raw in probe["items"]]
        before = len(load_manifest(args.manifest).get("items", {}))
        manifest = merge_items_into_manifest(items, args.manifest)
        after = len(manifest.get("items", {}))
        print(f"Manifest     : {args.manifest} ({before} -> {after})")

    if not probe["items"]:
        print("No video-like favorites found. Run with --headed --screenshot to inspect the logged-in page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

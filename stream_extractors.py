from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


YTDLP_HOST_HINTS = (
    "bilibili.com",
    "live.bilibili.com",
    "douyin.com",
    "iesdouyin.com",
    "douyu.com",
    "huya.com",
    "kuaishou.com",
    "youtube.com",
    "youtu.be",
)

PLAYWRIGHT_HOST_HINTS = (
    "zhihu.com",
    "www.zhihu.com",
)

MEDIA_PATTERNS = (
    ".m3u8",
    ".mpd",
    ".flv",
    ".mp4",
    "live-stream",
    "playlist",
    "vzuu.com",
    "vdn",
)


@dataclass
class ExtractedStream:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    extractor: str = "direct"
    media_type: str = "unknown"
    page_url: str = ""
    note: str = ""


def infer_media_type(url: str) -> str:
    lowered = url.lower()
    if ".m3u8" in lowered:
        return "hls"
    if ".mpd" in lowered:
        return "dash"
    if ".flv" in lowered:
        return "flv"
    if ".mp4" in lowered:
        return "mp4"
    if lowered.startswith("rtmp://"):
        return "rtmp"
    if lowered.startswith("rtsp://"):
        return "rtsp"
    return "unknown"


def analyze_url_route(page_url: str, extractor: str = "auto") -> str:
    requested = (extractor or "auto").strip().lower()
    if requested != "auto":
        return requested
    host = (urlparse(page_url).hostname or "").lower()
    if any(host == hint or host.endswith("." + hint) for hint in YTDLP_HOST_HINTS):
        return "ytdlp"
    if any(host == hint or host.endswith("." + hint) for hint in PLAYWRIGHT_HOST_HINTS):
        return "playwright"
    return "playwright"


def _clean_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    skipped = {
        "accept-encoding",
        "content-length",
        "host",
        "connection",
    }
    cleaned = {}
    for key, value in headers.items():
        if not key or value is None:
            continue
        lowered = key.lower()
        if lowered in skipped or lowered.startswith(":"):
            continue
        cleaned[key] = str(value)
    return cleaned


def _score_media_url(url: str) -> int:
    lowered = url.lower()
    score = 0
    if ".m3u8" in lowered:
        score += 100
    if ".flv" in lowered:
        score += 90
    if ".mpd" in lowered:
        score += 80
    if ".mp4" in lowered:
        score += 60
    if "vzuu.com" in lowered or "vdn" in lowered:
        score += 30
    if "live" in lowered or "stream" in lowered or "playlist" in lowered:
        score += 20
    if re.search(r"\.(jpg|jpeg|png|gif|webp|css|js)(\?|$)", lowered):
        score -= 200
    return score


def _pick_ytdlp_url(info: dict) -> tuple[str, dict[str, str]]:
    candidates = []
    requested_formats = info.get("requested_formats") or []
    formats = requested_formats or info.get("formats") or []
    if info.get("url"):
        candidates.append((info["url"], info.get("http_headers") or {}, 1000))
    for fmt in formats:
        url = fmt.get("url")
        if not url:
            continue
        score = _score_media_url(url)
        if fmt.get("protocol") in ("m3u8", "m3u8_native"):
            score += 100
        if fmt.get("vcodec") != "none" and fmt.get("acodec") != "none":
            score += 20
        candidates.append((url, fmt.get("http_headers") or info.get("http_headers") or {}, score))

    if not candidates:
        return "", {}
    candidates.sort(key=lambda item: item[2], reverse=True)
    return candidates[0][0], _clean_headers(candidates[0][1])


def extract_with_ytdlp(page_url: str, cookies_browser: str = "") -> ExtractedStream:
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("yt-dlp 未安装。请先 pip install yt-dlp，或改用 --extractor playwright。") from e

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    browser = cookies_browser or os.environ.get("YTDLP_COOKIES_BROWSER", "").strip()
    if browser:
        ydl_opts["cookiesfrombrowser"] = (browser,)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(page_url, download=False)

    stream_url, headers = _pick_ytdlp_url(info)
    if not stream_url:
        raise RuntimeError("yt-dlp 未返回可播放媒体 URL")
    return ExtractedStream(
        url=stream_url,
        headers=headers,
        extractor="ytdlp",
        media_type=infer_media_type(stream_url),
        page_url=page_url,
    )


def _is_media_candidate(url: str) -> bool:
    lowered = url.lower()
    return any(pattern in lowered for pattern in MEDIA_PATTERNS) and _score_media_url(url) > 0


async def _activate_page_media(page) -> None:
    """Trigger lazy player/network code without requiring platform-specific selectors."""
    try:
        await page.mouse.move(640, 360)
        await page.mouse.wheel(0, 300)
        await page.wait_for_timeout(500)
        await page.mouse.wheel(0, -300)
    except Exception:
        pass
    try:
        await page.evaluate(
            """
            () => {
              for (const video of document.querySelectorAll('video')) {
                video.muted = true;
                const result = video.play();
                if (result && typeof result.catch === 'function') {
                  result.catch(() => {});
                }
              }
            }
            """
        )
    except Exception:
        pass


async def _extract_with_playwright_async(
    page_url: str,
    storage_state: str = "",
    save_storage_state: str = "",
    user_data_dir: str = "",
    headed: bool = False,
    timeout_ms: int = 20000,
    wait_seconds: float = 8.0,
) -> ExtractedStream:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError("playwright 未安装。请先 pip install playwright 并安装浏览器。") from e

    candidates: list[tuple[int, str, dict[str, str]]] = []

    async with async_playwright() as p:
        context_kwargs = {}
        state_path = storage_state or os.environ.get("PLAYWRIGHT_STORAGE_STATE", "").strip()
        profile_dir = user_data_dir or os.environ.get("PLAYWRIGHT_USER_DATA_DIR", "").strip()
        state_out_path = save_storage_state or os.environ.get("PLAYWRIGHT_SAVE_STORAGE_STATE", "").strip()
        if state_path and not profile_dir:
            context_kwargs["storage_state"] = state_path
        if profile_dir:
            context = await p.chromium.launch_persistent_context(
                profile_dir,
                headless=not headed,
                **context_kwargs,
            )
            browser = None
        else:
            browser = await p.chromium.launch(headless=not headed)
            context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        def on_request(request):
            url = request.url
            if _is_media_candidate(url):
                candidates.append((_score_media_url(url), url, _clean_headers(request.headers)))
                print(f"  [Playwright] media candidate: {infer_media_type(url)} {urlparse(url).hostname}")

        page.on("request", on_request)

        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(1500)
            await _activate_page_media(page)
            await page.wait_for_timeout(int(wait_seconds * 1000))
        finally:
            if state_out_path:
                Path(state_out_path).parent.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=state_out_path)
            await context.close()
            if browser:
                await browser.close()

    if not candidates:
        raise RuntimeError("Playwright 未截获 .m3u8/.mpd/.flv/.mp4 等媒体请求")
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, stream_url, headers = candidates[0]
    return ExtractedStream(
        url=stream_url,
        headers=headers,
        extractor="playwright",
        media_type=infer_media_type(stream_url),
        page_url=page_url,
    )


def extract_with_playwright(
    page_url: str,
    storage_state: str = "",
    save_storage_state: str = "",
    user_data_dir: str = "",
    headed: bool = False,
    timeout_ms: int = 20000,
    wait_seconds: float = 8.0,
) -> ExtractedStream:
    return asyncio.run(
        _extract_with_playwright_async(
            page_url,
            storage_state=storage_state,
            save_storage_state=save_storage_state,
            user_data_dir=user_data_dir,
            headed=headed,
            timeout_ms=timeout_ms,
            wait_seconds=wait_seconds,
        )
    )


def extract_stream(
    page_url: str,
    extractor: str = "auto",
    storage_state: str = "",
    save_storage_state: str = "",
    user_data_dir: str = "",
    headed: bool = False,
    timeout_ms: int = 20000,
    wait_seconds: float = 8.0,
    ytdlp_cookies_browser: str = "",
) -> ExtractedStream:
    route = analyze_url_route(page_url, extractor)
    if route == "ytdlp":
        return extract_with_ytdlp(page_url, cookies_browser=ytdlp_cookies_browser)
    if route == "playwright":
        return extract_with_playwright(
            page_url,
            storage_state=storage_state,
            save_storage_state=save_storage_state,
            user_data_dir=user_data_dir,
            headed=headed,
            timeout_ms=timeout_ms,
            wait_seconds=wait_seconds,
        )
    raise ValueError(f"Unsupported extractor: {extractor}")

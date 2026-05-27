from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse


REPO_ROOT = Path(__file__).resolve().parents[1]
TOUTIAO_CACHE_DIR = REPO_ROOT / "cache" / "toutiao"
TOUTIAO_PROBE_DIR = TOUTIAO_CACHE_DIR / "probes"
TOUTIAO_AUTH_STATE = TOUTIAO_CACHE_DIR / "auth_state.json"
TOUTIAO_MANIFEST = TOUTIAO_CACHE_DIR / "manifest.json"
TOUTIAO_VIDEO_DIR = REPO_ROOT / "Videos" / "short" / "toutiao"

DEFAULT_TOUTIAO_HOME_URL = "https://www.toutiao.com/"
DEFAULT_FAVORITES_URL = os.environ.get(
    "TOUTIAO_FAVORITES_URL",
    "https://www.toutiao.com/c/user/favourite/",
)

VIDEO_URL_PATTERNS = (
    "/video/",
    "/group/",
    "ixigua.com",
    "toutiao.com/video",
    "toutiao.com/group",
)

# Live-stream subdomains that match VIDEO_URL_PATTERNS but are not downloadable VOD.
LIVE_URL_BLOCKLIST = (
    "live.ixigua.com",
    "live.toutiao.com",
)

ANTI_DETECTION_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--disable-setuid-sandbox",
]

ANTI_DETECTION_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
"""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


@dataclass
class ToutiaoItem:
    item_id: str
    title: str
    detail_url: str
    source: str = "favorites"
    author: str = ""
    cover_url: str = ""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    TOUTIAO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TOUTIAO_PROBE_DIR.mkdir(parents=True, exist_ok=True)
    TOUTIAO_VIDEO_DIR.mkdir(parents=True, exist_ok=True)


def slugify(value: str, default: str = "toutiao") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return slug[:80] or default


def sha1_short(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def canonical_url(url: str, base_url: str = DEFAULT_TOUTIAO_HOME_URL) -> str:
    if not url:
        return ""
    joined = urljoin(base_url, url)
    parsed = urlparse(joined)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    path = re.sub(r"/+", "/", parsed.path or "/")
    return urlunparse((scheme, netloc, path, "", "", ""))


def extract_item_id(url: str) -> str:
    parsed = urlparse(url)
    text = parsed.path
    for pattern in (
        r"/video/(\d+)",
        r"/group/(\d+)",
        r"/item/(\d+)",
        r"(\d{12,})",
    ):
        match = re.search(pattern, text)
        if match:
            return f"toutiao-{match.group(1)}"
    return f"toutiao-{slugify(parsed.netloc)}-{sha1_short(url)}"


def looks_like_video_url(url: str) -> bool:
    lowered = url.lower()
    if not lowered.startswith(("http://", "https://")):
        return False
    if any(block in lowered for block in LIVE_URL_BLOCKLIST):
        return False
    return any(pattern in lowered for pattern in VIDEO_URL_PATTERNS)


def normalize_title(title: str, fallback: str) -> str:
    cleaned = re.sub(r"\s+", " ", (title or "").strip())
    return cleaned[:160] or fallback


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path = TOUTIAO_MANIFEST) -> dict:
    manifest = load_json(path, None)
    if isinstance(manifest, dict) and manifest.get("schema_version"):
        manifest.setdefault("items", {})
        return manifest
    return {
        "schema_version": "toutiao-favorites-manifest-v1",
        "created_at": now_iso(),
        "updated_at": "",
        "items": {},
    }


def save_manifest(manifest: dict, path: Path = TOUTIAO_MANIFEST) -> None:
    manifest["updated_at"] = now_iso()
    write_json(path, manifest)


def merge_items_into_manifest(items: list[ToutiaoItem], manifest_path: Path = TOUTIAO_MANIFEST) -> dict:
    manifest = load_manifest(manifest_path)
    records = manifest.setdefault("items", {})
    new_count = 0
    updated_count = 0
    for item in items:
        existing = records.get(item.item_id)
        if existing is None:
            records[item.item_id] = {
                "item_id": item.item_id,
                "title": item.title,
                "detail_url": item.detail_url,
                "source": item.source,
                "author": item.author,
                "cover_url": item.cover_url,
                "first_seen_at": now_iso(),
                "last_seen_at": now_iso(),
                "download_status": "pending",
                "local_path": "",
                "downloaded_at": "",
                "download_method": "",
                "last_error": "",
            }
            new_count += 1
        else:
            for key in ("title", "detail_url", "source", "author", "cover_url"):
                value = getattr(item, key)
                if value and existing.get(key) != value:
                    existing[key] = value
                    updated_count += 1
            existing["last_seen_at"] = now_iso()
    manifest["last_sync"] = {
        "at": now_iso(),
        "seen": len(items),
        "new": new_count,
        "updated_fields": updated_count,
    }
    save_manifest(manifest, manifest_path)
    return manifest


def storage_state_to_netscape_cookie_file(storage_state_path: Path) -> Path:
    data = load_json(storage_state_path, {})
    cookies = data.get("cookies") or []
    tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".cookies.txt", delete=False)
    with tmp:
        tmp.write("# Netscape HTTP Cookie File\n")
        for cookie in cookies:
            domain = str(cookie.get("domain") or "")
            if not domain:
                continue
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            path = str(cookie.get("path") or "/")
            secure = "TRUE" if cookie.get("secure") else "FALSE"
            expires = int(float(cookie.get("expires") or 0))
            name = str(cookie.get("name") or "")
            value = str(cookie.get("value") or "")
            tmp.write(
                "\t".join([domain, include_subdomains, path, secure, str(expires), name, value])
                + "\n"
            )
    return Path(tmp.name)


def build_playwright_context(browser, storage_state: Path | None = None):
    kwargs = {
        "viewport": {"width": 1280, "height": 900},
        "locale": "zh-CN",
        "user_agent": USER_AGENT,
    }
    if storage_state and storage_state.exists():
        kwargs["storage_state"] = str(storage_state)
    context = browser.new_context(**kwargs)
    context.add_init_script(ANTI_DETECTION_INIT_SCRIPT)
    return context

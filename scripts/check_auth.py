"""
Check whether the Playwright auth state is still valid for a given platform.

Reads the auth JSON, locates the platform's session cookie, and checks its expiry.

Exit codes:
  0 — valid (or no expiry set)
  1 — expired or key cookie missing → needs re-login
  2 — file unreadable / unexpected format (treated as warning, run anyway)

Usage:
  python scripts/check_auth.py <auth_state.json> [--platform zhihu|xiaoe]
"""

import json
import sys
import time
from pathlib import Path

WARN_THRESHOLD_S = 3600

PLATFORM_COOKIES = {
    "zhihu": "z_c0",
    "xiaoe": "ko_token",
}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--platform")]
    platform = "zhihu"
    for i, a in enumerate(sys.argv[1:]):
        if a == "--platform" and i + 2 < len(sys.argv):
            platform = sys.argv[i + 2]

    auth_path = Path(args[0]) if args else Path("zhihu_auth_state.json")
    cookie_name = PLATFORM_COOKIES.get(platform, "z_c0")

    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[auth] 无法读取 {auth_path}: {e}", flush=True)
        sys.exit(2)

    cookies = [c for c in data.get("cookies", []) if c.get("name") == cookie_name]
    if not cookies or not cookies[0].get("value"):
        print(
            f"[auth] {cookie_name} cookie not found or empty -- please re-login",
            flush=True,
        )
        sys.exit(1)

    exp = float(cookies[0].get("expires", -1))
    now = time.time()

    if exp < 0:
        print(f"[auth] {cookie_name} cookie valid (session cookie, no expiry)", flush=True)
        sys.exit(0)

    remaining = exp - now
    if remaining <= 0:
        print(
            f"[auth] {cookie_name} cookie expired {int(-remaining / 60)} min ago -- please re-login",
            flush=True,
        )
        sys.exit(1)

    if remaining < WARN_THRESHOLD_S:
        print(
            f"[auth] WARNING: {cookie_name} cookie expires in {int(remaining / 60)} min -- re-login after stream",
            flush=True,
        )
    else:
        print(
            f"[auth] {cookie_name} cookie valid, ~{int(remaining / 3600)}h remaining",
            flush=True,
        )
    sys.exit(0)


if __name__ == "__main__":
    main()

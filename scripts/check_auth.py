"""
Check whether the Zhihu Playwright auth state is still valid.

Reads the auth JSON, locates the z_c0 session cookie, and checks its expiry.

Exit codes:
  0 — valid (or no expiry set)
  1 — expired or z_c0 missing → needs re-login
  2 — file unreadable / unexpected format (treated as warning, run anyway)

Usage:
  python scripts/check_auth.py <auth_state.json>
"""
import json, sys, time
from pathlib import Path

WARN_THRESHOLD_S = 3600  # warn if cookie expires within 1 hour

def main() -> None:
    auth_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("zhihu_auth_state.json")

    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[auth] 无法读取 {auth_path}: {e}", flush=True)
        sys.exit(2)

    cookies = [c for c in data.get("cookies", []) if c.get("name") == "z_c0"]
    if not cookies:
        print("[auth] z_c0 cookie not found -- please re-login: python login_save_auth.py", flush=True)
        sys.exit(1)

    exp = float(cookies[0].get("expires", -1))
    now = time.time()

    if exp < 0:
        print("[auth] Cookie valid (session cookie, no expiry)", flush=True)
        sys.exit(0)

    remaining = exp - now
    if remaining <= 0:
        print(f"[auth] Cookie expired {int(-remaining / 60)} min ago -- please re-login: python login_save_auth.py", flush=True)
        sys.exit(1)

    if remaining < WARN_THRESHOLD_S:
        print(f"[auth] WARNING: Cookie expires in {int(remaining / 60)} min -- re-login after stream", flush=True)
    else:
        print(f"[auth] Cookie valid, ~{int(remaining / 3600)}h remaining", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()

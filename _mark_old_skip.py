import json

m = json.load(open("cache/toutiao/manifest.json", "r", encoding="utf-8"))
old_ids = [
    "toutiao-7640689163528765482", "toutiao-7640441326116339752",
    "toutiao-7640429864771650094", "toutiao-7615947326888084004",
    "toutiao-7579932773713248262",
]
for kid in old_ids:
    if kid in m["items"]:
        m["items"][kid]["download_status"] = "skip"
        m["items"][kid]["last_error"] = "permanently unavailable"
json.dump(m, open("cache/toutiao/manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

new_pending = [(k, v) for k, v in m["items"].items() if v.get("download_status") not in ("done", "skip")]
print(f"Remaining pending: {len(new_pending)}")
for k, v in new_pending[:5]:
    print(f"  {k} | {v['detail_url']}")
if len(new_pending) > 5:
    print(f"  ... and {len(new_pending) - 5} more")

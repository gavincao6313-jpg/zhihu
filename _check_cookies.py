"""Check all cookies and their domains in auth state."""
import json
from collections import Counter

state = json.load(open("cache/toutiao/auth_state.json", "r", encoding="utf-8"))
domains = Counter(c.get("domain", "?") for c in state["cookies"])

print(f"Total cookies: {len(state['cookies'])}")
print(f"Unique domains: {len(domains)}")
print()

for domain, count in domains.most_common():
    cookies_on_domain = [(c["name"], c.get("expires", "session")) for c in state["cookies"] if c.get("domain") == domain]
    print(f"=== {domain} ({count} cookies) ===")
    for name, exp in cookies_on_domain:
        exp_str = "session" if exp == -1 else str(exp)[:10]
        print(f"  {name} (expires: {exp_str})")

# Next-Run Approach Comparison

WIN user proposes a command-line approach; MAC user is writing a BAT wrapper.
This doc compares both for decision.

---

## Approach A: Direct Command Line (WIN)

```powershell
& d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe zhihuTTS_stream.py `
  --playwright-keepalive `
  --page-url "<LIVE_URL>" `
  --playwright-storage-state zhihu_auth_state.json `
  --playwright-save-storage-state zhihu_auth_state.json `
  --duration 0 --chunk-duration 60 `
  --name "zhihu-gaowei-agent" `
  --stream-work-dir "Videos\.stream" --cleanup-slices
```

| Pros | Cons |
|------|------|
| Zero new files to maintain | Must type/copy full command |
| All params visible — easy to tweak per run | Easy to forget `--playwright-storage-state` |
| No indirection — debug directly | Cross-platform path differences (`\` vs `/`, venv location) |

---

## Approach B: BAT / Shell Wrapper (MAC)

One file, takes only the live URL as argument:

```bat
@echo off
set VENV_PYTHON=d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe
set WORK_DIR=d:\zhihu\zhihu_url
set STORAGE_STATE=zhihu_auth_state.json

cd /d %WORK_DIR%
%VENV_PYTHON% zhihuTTS_stream.py ^
  --playwright-keepalive ^
  --page-url "%1" ^
  --playwright-storage-state %STORAGE_STATE% ^
  --playwright-save-storage-state %STORAGE_STATE% ^
  --duration 0 --chunk-duration 60 ^
  --name "zhihu-gaowei-agent" ^
  --stream-work-dir Videos\.stream --cleanup-slices
```

Usage: `run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/..."`
- `--name` could also accept `%2` as optional second argument.

| Pros | Cons |
|------|------|
| One-click / one-command with URL only | New file to maintain |
| Encodes machine-specific paths (venv) | Must match each platform (`.bat` vs `.sh`) |
| Hard to forget auth args | Params hidden — user can't see what flags are used |
| Good for non-technical users | Debugging requires reading the wrapper |

---

## Verdict: Both, Layered

They serve different purposes and don't conflict:

1. **Wrapper script** (`run_zhihu_live.bat` / `run_zhihu_live.sh`) — daily driver, one arg
2. **Documentation** (`zhihu-live-discovery-20260518.md` §10) — full command for reference, debugging, or unusual runs

The wrapper is a thin convenience layer on top of the documented command.
They should stay in sync — wrapper is the encoded form of the doc command.

### What the wrapper must NOT hardcode
- `--name` — differs per live topic
- `--chunk-duration` — might want to experiment with 30s vs 60s

### What the wrapper SHOULD hardcode
- venv python path (machine-specific)
- `--playwright-storage-state` / `--playwright-save-storage-state` (always needed)
- `--stream-work-dir` (always the same)
- `--cleanup-slices` (always wanted in live mode)
- `--duration 0` (live mode default)

---

## Recommendation

Ship both:
- `run_zhihu_live.bat` — committed, WIN user's one-click entry
- `run_zhihu_live.sh` — committed, MAC user's equivalent
- Doc §10 keeps the full command reference

WIN side already has `zhihu_auth_state.json` saved (5340 bytes, gitignored).
First run after pulling: the wrapper will open browser, load cookies, and start.

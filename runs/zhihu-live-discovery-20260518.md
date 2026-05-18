# Zhihu Live Stream — Discovery & Integration Record

Date: 2026-05-18
Target: https://www.zhihu.com/xen/training/live/room/2013265166804997499/2013265169342537989?is_hybrid=1
Live: 通过情绪陪伴类智能体，学习多agent、多模态和语言风格化 (Teacher: 高玮)

---

## 1. Phase 1 — Environment Preparation

- Confirmed `zhihu_file\.venv-sensevoice` has all deps: funasr 1.3.1, playwright, yt-dlp, torch
- Cleaned 195 MB old test files from `Videos\.stream`
- `zhihu_url` has no venv — all processing uses zhihu_file's venv

## 2. Phase 2 — Authentication Discovery (4 failed approaches → 1 success)

### Attempt 1: Direct Playwright (FAILED)
- Playwright default launch → zhihu redirects to signin
- Login blocked: captcha API returns 403 (anti-bot detection)
- zhihu detects `navigator.webdriver` and automation flags

### Attempt 2: Chrome Profile via persistent_context (FAILED)
- Used `launch_persistent_context(channel="chrome", user_data_dir=...)` 
- Error: `Timeout 180000ms exceeded` — Chrome DevTools protocol conflict
- Background Chrome processes survive `Stop-Process`, new Chrome uses existing session without `--remote-debugging-port`

### Attempt 3: CDP connect_over_cdp (FAILED)
- Launched Chrome with `--remote-debugging-port=9222`
- `BrowserType.connect_over_cdp`: "Unexpected status 400 — This does not look like a DevTools server"
- Port 9222 not listening despite Chrome running with the flag
- Root cause: Windows Chrome ignores `--remote-debugging-port` when background processes exist

### Attempt 4: browser-cookie3 / pywin32 (NOT ATTEMPTED)
- `pywin32` not installed in venv
- `browser-cookie3` pip install failed
- Cookie decryption approach abandoned

### Attempt 5: Playwright + Anti-Detection (SUCCESS ✅)
```python
browser = p.chromium.launch(
    headless=False,
    args=["--disable-blink-features=AutomationControlled", ...],
)
page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
""")
```
- User logged in via QR code successfully
- Auth state saved to `zhihu_auth_state.json` (18 cookies including z_c0)

## 3. Phase 3 — Stream Format Discovery

### Architecture
```
Zhihu Page → CC Player SDK (csslcloud.net) → FLV Live Stream
```

### Key API Endpoints Discovered
| Endpoint | Purpose |
|----------|---------|
| `view.csslcloud.net/live/user/login` | CC authentication (returns session token) |
| `view.csslcloud.net/live/data?roomId=...` | Room metadata (status, resolution, IM servers) |
| `view.csslcloud.net/api/live/play?types=flv` | Returns FLV stream URLs with auth_key |
| `sio-39.csslcloud.net/socket.io/` | Chat/interaction WebSocket |
| `logger.csslcloud.net/event/live/v1/client` | Telemetry |
| `stream-ali1.csslcloud.net/src/{roomId}.flv?auth_key=...` | Primary CDN (Aliyun) |
| `stream-nws.csslcloud.net/src/{roomId}.flv?wsSecret=...` | Backup CDN |

### Stream Specs
- Format: FLV over HTTP
- Video: H.264 (High), 1920×1080, 15 fps, ~2048 kbps
- Audio: AAC LC, 44100 Hz, stereo, ~65 kbps
- Auth key expires: ~8 hours from stream start (timestamp in auth_key)

### Two Quality Levels
- Quality 0 (original): `{roomId}.flv` 
- Quality 500 (HD): `{roomId}_cfd-v.flv`

### Video Element
- Uses `blob:` URL (Media Source Extensions) — NOT usable directly
- CC player SDK: fetches FLV chunks → feeds to MSE → video element renders
- Raw FLV URL IS captured as `[media]` type network request — usable by pipeline

## 4. Phase 4 — Pipeline Integration

### Code Change Required
`zhihuTTS_stream.py:slice_url()` — skip `-ss` for live FLV:
```python
is_live = infer_media_type(url) in ("flv",)
if not is_live:
    cmd += ["-ss", fmt_time(start_s)]
```
Reason: live FLV streams don't support seeking. `-ss 0` causes "could not seek to position" error.

### Smoke Test Results (2 chunks × 30s)
```
Chunk 1: 30s → SenseVoice 1 segment, rtf_avg=0.055, 30 frames, elapsed 41.08s
Chunk 2: 30s → SenseVoice 1 segment, rtf_avg=0.054, 30 frames, elapsed 33.77s
Status: PASS ✅
```

### Working Command
```bash
python zhihuTTS_stream.py \
  --url "https://stream-ali1.csslcloud.net/src/{roomId}.flv?auth_key=..." \
  --duration 0 --chunk-duration 60 \
  --name "zhihu-gaowei-agent" \
  --stream-work-dir "Videos\.stream" --cleanup-slices
```

## 5. Files Created

| File | Purpose |
|------|---------|
| `login_save_auth.py` | Playwright + anti-detection, QR login, save auth state |
| `monitor_zhihu_live.py` | Full pipeline: login → live room → poll → capture stream URL |
| `detect_stream_format.py` | Network analysis — captures ALL requests to identify stream mechanism |
| `probe_zhihu_live.py` | CDP-based probe (requires chrome --remote-debugging-port) |
| `login_zhihu.py` | Interactive login helper |
| `zhihu_auth_state.json` | Saved Playwright auth (18 cookies) — gitignored |
| `.last_stream_url.txt` | Latest FLV URL with auth_key — gitignored |
| `.stream_detection.json` | Raw detection data from working session |
| `runs/stream-zhihu-live-test-*` | Smoke test output (manifest, transcripts, reports) |

## 6. Open Issues for Mac User

### P0 — PlaywrightKeepaliveStream needs anti-detection
`stream_extractors.py:PlaywrightKeepaliveStream` uses plain Playwright without anti-detection measures. Zhihu will block it. Need to add:
```python
# In _navigate() or start():
page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    ...
""")
```
And launch args: `--disable-blink-features=AutomationControlled`

### P1 — FLV auth_key refresh
The `--url` direct approach works, but auth_key expires (~8h). `--playwright-keepalive` should auto-refresh via CC API calls, but needs the anti-detection fix above.

### P1 — CC API integration
Could call `view.csslcloud.net/api/live/play?types=flv` directly (with CC session token) instead of Playwright page interception. The CC session token is obtained from `view.csslcloud.net/live/user/login` which uses zhihu's accountId + roomId. This would be more reliable than network interception.

### P2 — CDP on Windows
`chrome --remote-debugging-port=9222` doesn't work reliably on Windows 10. Background Chrome processes survive `Stop-Process`. Alternative: use a separate user-data-dir with the flag.

## 7. Current Status

- [x] Zhihu auth flow understood and working
- [x] Stream format identified (CC csslcloud FLV)
- [x] Pipeline integration tested (2 chunks smoke test PASS)
- [x] All code and data pushed to remote
- [ ] Full live-mode run (--duration 0) not yet executed
- [ ] PlaywrightKeepaliveStream anti-detection not yet added
- [ ] CC API direct integration not yet attempted

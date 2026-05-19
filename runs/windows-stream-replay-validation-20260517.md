# Windows Stream Replay Validation Handoff - 2026-05-17

## Status

- Mac only completed remote media probing.
- Full replay-stream validation should run on Windows because the Mac hardware is not suitable for a multi-hour Whisper validation run.
- Do not run this validation from `main`; use `feature/stream-transcript-validation`.
- Do not commit the signed replay URL or any `pkey`/cookie/header secrets.

## Mac Probe Result

- Host: `vdn6.vzuu.com`
- Container: MP4 / QuickTime MOV
- Duration: `02:42:53`
- Size: `309342920` bytes
- Video: H.264, `1920x1080`, about `15 fps`
- Audio: AAC HE-AAC, `44100 Hz`, stereo
- Probe result: readable by `ffprobe` when network access is allowed.

## Windows Commands

Run from the repo root on Windows:

```powershell
git fetch origin
git switch feature/stream-transcript-validation
git pull --ff-only
python zhihuTTS_stream.py --help
```

Set the replay URL locally. Keep it out of Git and reports:

```powershell
$env:REPLAY_URL = '<paste signed replay MP4 URL here>'
```

Optional preflight:

```powershell
ffprobe -hide_banner -v warning -show_format -show_streams $env:REPLAY_URL
```

Full replay validation:

```powershell
python zhihuTTS_stream.py `
  --url $env:REPLAY_URL `
  --start 0 `
  --duration 0 `
  --chunk-duration 300 `
  --name replay-full `
  --no-gemini
```

## Expected Outputs

The stream runner writes outputs under `runs/`:

- `stream-replay-full-*.combined-transcript.txt`
- `stream-replay-full-*.manifest.md`
- `stream-replay-full-*.manifest.json`
- Per-chunk transcript/report/payload files

Each chunk is 5 minutes. The source duration is about 163 minutes, so expect about 33 chunks.

## Validation Notes

- This script does not call Gemini.
- The validation checks remote slicing, keyframe extraction, Whisper transcription, timestamp offsetting, combined transcript generation, and manifest generation.
- If the URL expires, ask for a fresh signed replay URL and rerun from the start.
- If a chunk fails, preserve the console output and the latest generated `runs/stream-replay-full-*` files for diagnosis.

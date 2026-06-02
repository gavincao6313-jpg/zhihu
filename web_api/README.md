# zhihu web API

This is the first local API layer for the frontend workbench.

Current P0 behavior:

- scans `runs/*.final-qc.json`
- links matching manifests, transcripts, Markdown files, chunks, and payload frames
- exposes `GET /api/runs`
- exposes `GET /api/runs/{id}`
- exposes `POST /api/run-plans` for dry-run command/path previews; it does not start long-running capture, ASR, or model calls
- exposes `POST /api/runs` to save a dry-run plan as a local `created` run in `runs/web-run-registry.json`; it still does not start long-running work

Run locally:

```bash
python3 web_api/server.py
```

The Vite frontend proxies `/api` to `http://127.0.0.1:8765`.

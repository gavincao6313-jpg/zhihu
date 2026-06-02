from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"
MARKDOWNS_DIR = ROOT / "Markdowns"
REGISTRY_PATH = RUNS_DIR / "web-run-registry.json"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_text(path: Path, limit: int = 8000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except Exception:
        return ""


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def source_type_from_base(base: str) -> str:
    if "replay" in base:
        return "replay"
    if base.startswith("live") or "stream-live" in base:
        return "live"
    return "mp4"


def safe_base(value: str, fallback: str) -> str:
    text = value.strip() or fallback
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"[\\/:*?\"<>|#&=%]+", "-", text)
    text = re.sub(r"\s+", "-", text).strip(".-")
    return text[:80] or fallback


def parse_qc_path(path: Path) -> tuple[str, str, str]:
    name = path.name
    match = re.match(r"stream-(.+?)-(\d{8}-\d{6})(?:\.([^.]+))?\.final-qc\.json$", name)
    if not match:
        return name.replace(".final-qc.json", ""), "", ""
    return match.group(1), match.group(2), match.group(3) or ""


def newest(candidates: list[Path]) -> Path | None:
    return sorted(candidates, key=lambda item: (item.stat().st_mtime, item.name))[-1] if candidates else None


def markdown_for_base(base: str, label: str = "") -> Path | None:
    if label:
        exact = MARKDOWNS_DIR / f"TTS_stream-{base}-{label}.md"
        if exact.exists():
            return exact
        exact = MARKDOWNS_DIR / f"TTS_{base}-{label}.md"
        if exact.exists():
            return exact

    candidates = sorted(MARKDOWNS_DIR.glob(f"TTS_stream-{base}*.md"))
    if not candidates:
        candidates = sorted(MARKDOWNS_DIR.glob(f"TTS_{base}*.md"))
    return newest(candidates)


def manifest_for_base(base: str) -> Path | None:
    return newest(list(RUNS_DIR.glob(f"stream-{base}-*.manifest.json")))


def transcript_for_base(base: str) -> Path | None:
    return newest(list(RUNS_DIR.glob(f"stream-{base}-*.combined-transcript.txt")))


def local_runs_path(value: str) -> Path | None:
    if not value:
        return None
    name = Path(value.replace("\\", "/")).name
    path = RUNS_DIR / name
    return path if path.exists() else None


def manifest_chunks(manifest_path: Path | None) -> list[dict]:
    if not manifest_path:
        return []
    data = read_json(manifest_path)
    chunks = data.get("chunks")
    return chunks if isinstance(chunks, list) else []


def chunks_from_manifest(manifest_path: Path | None) -> list[dict]:
    chunks = []
    for item in manifest_chunks(manifest_path)[:250]:
        outputs = item.get("outputs") or {}
        processing = item.get("processing") or {}
        chunk_meta = item.get("chunk") or {}
        slice_meta = item.get("slice") or {}
        report = local_runs_path(outputs.get("report_md", ""))
        payload = local_runs_path(outputs.get("payload_json", ""))
        transcript = local_runs_path(outputs.get("transcript_txt", ""))
        transcript_text = read_text(transcript, limit=200000) if transcript else ""
        chunks.append(
            {
                "index": int(chunk_meta.get("index") or len(chunks) + 1),
                "start_s": int(float(slice_meta.get("start_s") or 0)),
                "duration_s": int(float(slice_meta.get("duration_s") or 60)),
                "transcript_chars": int(processing.get("transcript_chars") or len(transcript_text)),
                "segments": int(processing.get("segments") or transcript_text.count("[")),
                "frames": int(processing.get("frames") or 0),
                "reextracts": int(processing.get("stream_reextracts") or 0),
                "backend": processing.get("backend") or "unknown",
                "report_path": str(report.relative_to(ROOT)) if report else "",
                "transcript_path": str(transcript.relative_to(ROOT)) if transcript else "",
                "payload_path": str(payload.relative_to(ROOT)) if payload else "",
            }
        )
    return chunks


def chunks_for_base(base: str, manifest_path: Path | None = None) -> list[dict]:
    manifest_records = chunks_from_manifest(manifest_path)
    if manifest_records:
        return manifest_records

    chunks = []
    for report in sorted(RUNS_DIR.glob(f"stream-{base}_chunk*.md"))[:250]:
        match = re.search(r"_chunk(\d+)_(\d+)s-", report.name)
        if not match:
            continue
        index = int(match.group(1))
        start_s = int(match.group(2))
        payload = report.with_suffix(".payload.json")
        transcript = report.with_suffix(".transcript.txt")
        payload_data = read_json(payload)
        frames = payload_data.get("frames") or payload_data.get("visual_evidence") or []
        transcript_text = read_text(transcript, limit=200000)
        chunks.append(
            {
                "index": index,
                "start_s": start_s,
                "duration_s": 60,
                "transcript_chars": len(transcript_text),
                "segments": transcript_text.count("["),
                "frames": len(frames),
                "reextracts": 0,
                "backend": "unknown",
                "report_path": str(report.relative_to(ROOT)),
                "transcript_path": str(transcript.relative_to(ROOT)) if transcript.exists() else "",
                "payload_path": str(payload.relative_to(ROOT)) if payload.exists() else "",
            }
        )
    return chunks


def payloads_from_manifest(manifest_path: Path | None) -> list[tuple[Path, int | None, int]]:
    payloads = []
    for item in manifest_chunks(manifest_path):
        outputs = item.get("outputs") or {}
        chunk_meta = item.get("chunk") or {}
        slice_meta = item.get("slice") or {}
        payload = local_runs_path(outputs.get("payload_json", ""))
        if payload:
            payloads.append((payload, chunk_meta.get("index"), int(float(slice_meta.get("start_s") or 0))))
    return payloads


def frames_for_base(base: str, manifest_path: Path | None = None) -> list[dict]:
    frames = []
    payloads = payloads_from_manifest(manifest_path)
    if not payloads:
        payloads = []
        for payload in sorted(RUNS_DIR.glob(f"stream-{base}_chunk*.payload.json"))[:120]:
            match = re.search(r"_chunk(\d+)_(\d+)s-", payload.name)
            chunk_index = int(match.group(1)) if match else None
            chunk_start = int(match.group(2)) if match else 0
            payloads.append((payload, chunk_index, chunk_start))

    for payload, chunk_index, chunk_start in payloads[:120]:
        match = re.search(r"_chunk(\d+)_(\d+)s-", payload.name)
        if chunk_index is None:
            chunk_index = int(match.group(1)) if match else None
        if not chunk_start:
            chunk_start = int(match.group(2)) if match else 0
        data = read_json(payload)
        records = data.get("frames") or data.get("visual_evidence") or []
        for record in records[:4]:
            ts = record.get("timestamp_s") or record.get("time_s") or record.get("ts") or 0
            kind = record.get("type") or record.get("kind") or "context"
            if kind not in {"slide", "annotation", "context"}:
                kind = "context"
            frames.append(
                {
                    "timestamp_s": chunk_start + float(ts),
                    "type": kind,
                    "path": str(payload.relative_to(ROOT)),
                    "chunk_index": chunk_index,
                    "selected": True,
                }
            )
    return frames[:240]


def build_steps(
    qc: dict,
    chunk_count: int,
    markdown_path: Path | None,
    manifest_path: Path | None,
    transcript_path: Path | None,
) -> list[dict]:
    warnings = qc.get("warnings") or []
    source_status = qc.get("source_status") or "unknown"
    coverage_status = qc.get("body_coverage_status") or "unknown"
    source_done = bool(manifest_path or qc)
    qc_status = "warning" if warnings or coverage_status not in {"unknown", "ok"} else "done"
    return [
        {"key": "source", "label": "Source", "status": "done" if source_done else "pending", "summary": f"source_status={source_status}"},
        {"key": "record", "label": "Capture", "status": "done" if chunk_count else "pending", "summary": f"{chunk_count} chunks indexed"},
        {"key": "transcript", "label": "Transcript", "status": "done" if transcript_path else "pending", "summary": "Combined transcript available" if transcript_path else "No combined transcript"},
        {"key": "frames", "label": "Keyframes", "status": "done" if qc.get("frame_count", 0) else "pending", "summary": f"{qc.get('frame_count', 0)} frames in QC"},
        {"key": "qc", "label": "QC", "status": qc_status, "summary": f"{len(warnings)} warnings, coverage={coverage_status}"},
        {"key": "markdown", "label": "Markdown", "status": "done" if markdown_path else "pending", "summary": "Final Markdown available" if markdown_path else "No final Markdown"},
    ]


def created_steps(plan: dict) -> list[dict]:
    warnings = plan.get("warnings") or []
    command_count = len(plan.get("commands") or [])
    return [
        {"key": "source", "label": "Source", "status": "warning" if warnings else "done", "summary": f"{plan.get('source_type', 'source')} input planned"},
        {"key": "record", "label": "Capture", "status": "pending", "summary": "Not started"},
        {"key": "transcript", "label": "Transcript", "status": "pending", "summary": "Waiting for capture output"},
        {"key": "frames", "label": "Keyframes", "status": "pending", "summary": "Waiting for payload frames"},
        {"key": "qc", "label": "QC", "status": "pending", "summary": "No final QC yet"},
        {"key": "markdown", "label": "Markdown", "status": "pending", "summary": f"{command_count} planned commands"},
    ]


def status_from_qc(qc: dict) -> str:
    warnings = qc.get("warnings") or []
    source_status = qc.get("source_status")
    coverage_status = qc.get("body_coverage_status")
    if qc.get("success") is False or source_status in {"failed", "error", "missing"}:
        return "failed"
    if warnings or coverage_status not in {None, "", "ok"}:
        return "warning"
    return "completed"


def run_from_qc(path: Path, include_detail: bool = True) -> dict:
    base, run_ts, label = parse_qc_path(path)
    qc = read_json(path)
    markdown_path = markdown_for_base(base, label)
    manifest_path = manifest_for_base(base)
    transcript_path = transcript_for_base(base)
    chunks = chunks_for_base(base, manifest_path) if include_detail else []
    frames = frames_for_base(base, manifest_path) if include_detail else []
    warnings = qc.get("warnings") or []
    transcript_text = read_text(transcript_path, limit=250000) if transcript_path and include_detail else ""
    transcript_preview = transcript_text[:6000] if include_detail else ""
    markdown_preview = read_text(markdown_path, limit=6000) if markdown_path and include_detail else ""
    manifest_chunk_count = len(manifest_chunks(manifest_path))
    chunk_count = len(chunks) if include_detail else manifest_chunk_count or len(list(RUNS_DIR.glob(f"stream-{base}_chunk*.md")))
    return {
        "id": path.stem,
        "base": base,
        "source_type": source_type_from_base(base),
        "status": status_from_qc(qc),
        "created_at": run_ts,
        "updated_at": run_ts or str(int(path.stat().st_mtime)),
        "provider": qc.get("synthesis_provider"),
        "model": qc.get("synthesis_model"),
        "synthesis_pass": qc.get("synthesis_pass"),
        "label": label,
        "paths": {
            "manifest_json": str(manifest_path.relative_to(ROOT)) if manifest_path else "",
            "combined_transcript": str(transcript_path.relative_to(ROOT)) if transcript_path else "",
            "final_qc": str(path.relative_to(ROOT)),
            "markdown": str(markdown_path.relative_to(ROOT)) if markdown_path else "",
        },
        "metrics": {
            "chunks": chunk_count,
            "transcript_chars": len(transcript_text) if include_detail else (transcript_path.stat().st_size if transcript_path else 0),
            "frames": qc.get("frame_count", len(frames)),
            "warnings": len(warnings),
        },
        "steps": build_steps(qc, chunk_count, markdown_path, manifest_path, transcript_path),
        "chunks": chunks,
        "frames": frames,
        "qc": {
            "source_status": qc.get("source_status"),
            "body_coverage_status": qc.get("body_coverage_status"),
            "body_tail_gap_s": qc.get("body_tail_gap_s"),
            "frame_count": qc.get("frame_count"),
            "warnings": warnings,
            "provider": qc.get("synthesis_provider"),
            "model": qc.get("synthesis_model"),
            "synthesis_pass": qc.get("synthesis_pass"),
            "qwen_window_policy": qc.get("qwen_window_policy"),
        },
        "transcript_preview": transcript_preview,
        "markdown_preview": markdown_preview,
    }


def list_runs() -> list[dict]:
    qc_files = [
        path
        for path in RUNS_DIR.glob("*.final-qc.json")
        if ".review-" not in path.name
    ]
    qc_files = sorted(qc_files, key=lambda path: path.stat().st_mtime, reverse=True)
    created = [record_to_run(record, include_detail=False) for record in list_registry_records()]
    # Registry runs take precedence: skip QC-backed runs that share the same base,
    # so a completed run doesn't appear twice once it produces a final-qc artifact.
    registered_bases = {r["base"] for r in created}
    completed = [
        run_from_qc(path, include_detail=False)
        for path in qc_files[:30]
        if parse_qc_path(path)[0] not in registered_bases
    ]
    return (created + completed)[:40]


def find_qc_by_id(run_id: str) -> Path | None:
    target = f"{run_id}.json" if not run_id.endswith(".json") else run_id
    path = RUNS_DIR / target
    if path.exists() and path.name.endswith(".final-qc.json"):
        return path
    for candidate in RUNS_DIR.glob("*.final-qc.json"):
        if candidate.stem == run_id:
            return candidate
    return None


def list_registry_records() -> list[dict]:
    data = read_json(REGISTRY_PATH)
    records = data.get("records")
    return records if isinstance(records, list) else []


def save_registry_record(record: dict) -> None:
    records = [item for item in list_registry_records() if item.get("id") != record.get("id")]
    records.insert(0, record)
    write_json(REGISTRY_PATH, {"version": 1, "records": records[:100]})


def find_registry_record(run_id: str) -> dict | None:
    normalized = run_id.removeprefix("web:")
    for record in list_registry_records():
        if record.get("id") == normalized or f"web:{record.get('id')}" == run_id:
            return record
    return None


def record_to_run(record: dict, include_detail: bool = True) -> dict:
    plan = record.get("plan") or {}
    warnings = plan.get("warnings") or []
    logs = record.get("logs") or []
    return {
        "id": f"web:{record.get('id')}",
        "base": plan.get("base") or record.get("id"),
        "source_type": plan.get("source_type") or "live",
        "status": record.get("status") or "created",
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at") or record.get("created_at"),
        "provider": plan.get("provider"),
        "model": None,
        "synthesis_pass": plan.get("synthesis_pass"),
        "label": plan.get("provider"),
        "paths": plan.get("paths") or {},
        "metrics": {
            "chunks": 0,
            "transcript_chars": 0,
            "frames": 0,
            "warnings": len(warnings),
        },
        "steps": created_steps(plan),
        "chunks": [],
        "frames": [],
        "qc": {
            "source_status": "planned",
            "body_coverage_status": "pending",
            "body_tail_gap_s": 0,
            "frame_count": 0,
            "warnings": warnings,
            "provider": plan.get("provider"),
            "model": None,
            "synthesis_pass": plan.get("synthesis_pass"),
            "qwen_window_policy": None,
        },
        "plan": plan if include_detail else None,
        "logs": logs if include_detail else [],
        "transcript_preview": "Created run. Transcript will appear after capture/transcription finishes.",
        "markdown_preview": "Created run. Final Markdown will appear after synthesis and QC finish.",
    }


def build_run_plan(payload: dict) -> dict:
    source_type = payload.get("source_type") or "live"
    source = str(payload.get("source") or "").strip()
    provider = payload.get("provider") or ("qwen" if source_type == "replay" else "gemini")
    synthesis_pass = payload.get("synthesis_pass") or ("sliding-window" if provider == "qwen" else "one-shot")
    qwen_max_frames = int(payload.get("qwen_max_frames") or 250)
    created_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = safe_base(str(payload.get("base") or ""), f"{source_type}-{stamp}")
    warnings: list[str] = []
    checks: list[dict] = []

    if not source:
        warnings.append("source is empty; paste a local path, replay payload, or live URL before starting.")
    if source_type == "mp4":
        candidate = Path(source).expanduser()
        if not candidate.is_absolute():
            candidate = ROOT / source
        checks.append({"key": "source_exists", "status": "ok" if candidate.exists() else "warning", "summary": str(candidate)})
        if not candidate.exists():
            warnings.append("MP4 path is not found on this machine; dry-run only can continue.")
        base = safe_base(str(payload.get("base") or candidate.stem), f"mp4-{stamp}")
    elif source_type == "replay":
        if not source.endswith(".json"):
            warnings.append("Replay URL acquisition is not fully wired in the local web API yet; current safe path expects an existing payload.json.")
        base = safe_base(str(payload.get("base") or Path(source).stem.replace(".payload", "")), f"replay-{stamp}")
    elif source_type == "live":
        if provider == "qwen":
            warnings.append("Current run_zhihu_live.bat is simplified Gemini-oriented; Qwen live finalization needs the provider wrapper restored or a manual build_stream_markdown.py fallback.")
        base = safe_base(str(payload.get("base") or f"live-{stamp}"), f"live-{stamp}")
    else:
        warnings.append(f"Unknown source_type={source_type}; expected mp4, replay, or live.")

    commands: list[dict] = []
    if source_type == "mp4":
        commands.append(
            {
                "stage": "process",
                "label": "Process MP4",
                "command": f"python3 run_single_file.py \"{source}\"",
                "summary": "Runs the existing local MP4 pipeline; this is preview-only and is not executed by the API.",
            }
        )
    elif source_type == "replay":
        commands.append(
            {
                "stage": "prepare",
                "label": "Prepare replay payload",
                "command": f"python3 scripts/convert_payload_to_chunks.py \"{source}\" \"{base}\" runs",
                "summary": "Converts an existing replay payload.json into stream chunk format.",
            }
        )
        commands.append(
            {
                "stage": "synthesize",
                "label": "Build Qwen Markdown",
                "command": f"python3 scripts/build_stream_markdown.py --base \"{base}\" --runs-dir runs --markdowns-dir Markdowns --provider {provider} --synthesis-pass {synthesis_pass} --qwen-max-frames {qwen_max_frames} --output-label {provider}",
                "summary": "Generates the final NotebookLM Markdown after replay chunks exist.",
            }
        )
    elif source_type == "live":
        commands.append(
            {
                "stage": "capture",
                "label": "Capture live stream",
                "command": f"run_zhihu_live.bat \"{source}\" \"{base}\"",
                "summary": "Windows operator entrypoint for live capture and post-processing.",
            }
        )
        commands.append(
            {
                "stage": "review",
                "label": "Refresh workbench index",
                "command": "Open http://127.0.0.1:5173/ and press Refresh index",
                "summary": "The UI will discover final QC, transcript, chunks, keyframes, and Markdown after artifacts land.",
            }
        )

    paths = {
        "manifest_json": f"runs/stream-{base}-<run_ts>.manifest.json",
        "combined_transcript": f"runs/stream-{base}-<run_ts>.combined-transcript.txt",
        "final_qc": f"runs/stream-{base}-<run_ts>.{provider}.final-qc.json",
        "markdown": f"Markdowns/TTS_stream-{base}-{provider}.md" if source_type != "mp4" else f"Markdowns/TTS_<date>_{base}.md",
    }
    return {
        "id": f"dry-{base}-{stamp}",
        "dry_run": True,
        "created_at": created_at,
        "source_type": source_type,
        "source": source,
        "base": base,
        "provider": provider,
        "synthesis_pass": synthesis_pass,
        "qwen_max_frames": qwen_max_frames,
        "warnings": warnings,
        "checks": checks,
        "commands": commands,
        "paths": paths,
    }


def create_registry_record(payload: dict) -> dict:
    plan = build_run_plan(payload)
    created_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    record = {
        "id": plan["id"].removeprefix("dry-"),
        "status": "created",
        "created_at": created_at,
        "updated_at": created_at,
        "plan": plan,
        "logs": [
            {"time": created_at, "level": "info", "message": "Dry-run plan saved as a created run."},
            {"time": created_at, "level": "info", "message": "No capture, ASR, or model call has been started."},
        ],
    }
    save_registry_record(record)
    return record_to_run(record, include_detail=True)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self) -> None:
        self.send_json({"ok": True})

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/runs":
            self.send_json(list_runs())
            return
        if path.startswith("/api/runs/"):
            run_id = path.removeprefix("/api/runs/")
            registry_record = find_registry_record(run_id)
            if registry_record:
                self.send_json(record_to_run(registry_record, include_detail=True))
                return
            qc_path = find_qc_by_id(run_id)
            if not qc_path:
                self.send_json({"error": "run not found"}, status=404)
                return
            self.send_json(run_from_qc(qc_path, include_detail=True))
            return
        self.send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/run-plans":
            self.send_json(build_run_plan(self.read_json_body()))
            return
        if path == "/api/runs":
            self.send_json(create_registry_record(self.read_json_body()), status=201)
            return
        self.send_json({"error": "not found"}, status=404)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("zhihu web_api listening on http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()

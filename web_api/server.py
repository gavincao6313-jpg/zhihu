from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"
MARKDOWNS_DIR = ROOT / "Markdowns"
REGISTRY_PATH = RUNS_DIR / "web-run-registry.json"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CLEANUP_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")  # keep \n \t \r

# Thread-safe registry access — prevents race condition between HTTP poller
# and pipeline daemon thread writing status updates simultaneously.
_REGISTRY_LOCK = threading.Lock()

# Populated by main() from CLI args; controls write access and launch mode.
_READONLY: bool = False
_LAUNCH_MODE: str = "simulate"  # "simulate" | "live"


def _rel(path: Path) -> str:
    """Return a posix-style relative path for API responses (safe on both WIN and MAC)."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


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


def manifest_for_base(base: str, run_ts: str = "") -> Path | None:
    if run_ts:
        exact = RUNS_DIR / f"stream-{base}-{run_ts}.manifest.json"
        if exact.exists():
            return exact
    return newest(list(RUNS_DIR.glob(f"stream-{base}-*.manifest.json")))


def transcript_for_base(base: str, run_ts: str = "") -> Path | None:
    if run_ts:
        exact = RUNS_DIR / f"stream-{base}-{run_ts}.combined-transcript.txt"
        if exact.exists():
            return exact
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
                "report_path": _rel(report) if report else "",
                "transcript_path": _rel(transcript) if transcript else "",
                "payload_path": _rel(payload) if payload else "",
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
                "report_path": _rel(report),
                "transcript_path": _rel(transcript) if transcript.exists() else "",
                "payload_path": _rel(payload) if payload.exists() else "",
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
            kind = record.get("type") or record.get("kind") or ""
            if kind not in {"slide", "annotation", "context"}:
                # Payload marker carries type when the field is empty, e.g.
                # "Frame [00:00:37] type=slide diff=0.8"
                marker = str(record.get("marker") or "")
                m = re.search(r"type=(\w+)", marker)
                kind = m.group(1) if m and m.group(1) in {"slide", "annotation", "context"} else "context"
            img_path = _resolve_frame_path(str(record.get("path") or ""))
            frames.append(
                {
                    "timestamp_s": chunk_start + float(ts),
                    "type": kind,
                    "path": img_path,
                    "chunk_index": chunk_index,
                    "selected": True,
                }
            )
    return frames[:240]


def _resolve_frame_path(raw: str) -> str:
    """Convert a payload frame path (possibly absolute WIN path) to a posix relative path.

    Payload stores absolute paths like D:\\zhihu\\zhihu_url\\Videos\\keyframes\\...
    We make them relative to ROOT so /api/frames can serve them cross-platform.
    """
    if not raw:
        return ""
    normalised = raw.replace("\\", "/")
    p = Path(normalised)
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        pass
    # Strip leading drive + project dir by finding a known top-level folder
    parts = p.parts
    for anchor in ("Videos", "runs", "Markdowns", "cache"):
        try:
            idx = parts.index(anchor)
            return "/".join(parts[idx:])
        except ValueError:
            continue
    return normalised


def _locate_frame_file(img_rel: str) -> Path | None:
    """Find an image file by its relative path.

    Searches ROOT first, then sibling worktree directories (same parent folder).
    This handles the WIN dual-worktree layout where the API runs from one worktree
    (e.g. zhihu_file) but frame images live in another (e.g. zhihu_url).
    """
    _ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

    def _safe_candidate(base: Path) -> Path | None:
        candidate = (base / img_rel).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError:
            return None
        if candidate.suffix.lower() in _ALLOWED_SUFFIXES and candidate.exists():
            return candidate
        return None

    # 1. Try ROOT (fast path, covers same-worktree deployments)
    found = _safe_candidate(ROOT)
    if found:
        return found

    # 2. Try sibling directories of ROOT's parent (handles cross-worktree on WIN)
    parent = ROOT.parent
    try:
        siblings = [d for d in parent.iterdir() if d.is_dir() and d != ROOT]
    except PermissionError:
        siblings = []
    for sibling in sorted(siblings):
        found = _safe_candidate(sibling)
        if found:
            return found

    return None


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
    manifest_path = manifest_for_base(base, run_ts)
    transcript_path = transcript_for_base(base, run_ts)
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
            "manifest_json": _rel(manifest_path) if manifest_path else "",
            "combined_transcript": _rel(transcript_path) if transcript_path else "",
            "final_qc": _rel(path),
            "markdown": _rel(markdown_path) if markdown_path else "",
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


def run_from_mp4_md(md_path: Path, include_detail: bool = True) -> dict:
    """Build a RunRecord from a local MP4 Markdown output (no QC file)."""
    stem = md_path.stem                      # e.g. "TTS_0602_MyVideo"
    base = stem.removeprefix("TTS_")         # e.g. "0602_MyVideo"
    mtime = int(md_path.stat().st_mtime)
    markdown_preview = read_text(md_path, limit=6000) if include_detail else ""
    return {
        "id": stem,
        "base": stem,
        "source_type": "mp4",
        "status": "completed",
        "created_at": str(mtime),
        "updated_at": str(mtime),
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "synthesis_pass": "one-shot",
        "label": "gemini",
        "paths": {
            "markdown": _rel(md_path),
            "manifest_json": "",
            "combined_transcript": "",
            "final_qc": "",
        },
        "metrics": {"chunks": 0, "transcript_chars": 0, "frames": 0, "warnings": 0},
        "steps": [
            {"key": "source",    "label": "Source",    "status": "done",    "summary": "Local MP4 file"},
            {"key": "synthesis", "label": "Synthesis", "status": "done",    "summary": "Gemini one-shot"},
            {"key": "markdown",  "label": "Markdown",  "status": "done",    "summary": _rel(md_path)},
        ],
        "chunks": [],
        "frames": [],
        "qc": {
            "source_status": "full",
            "body_coverage_status": "ok",
            "body_tail_gap_s": 0,
            "frame_count": 0,
            "warnings": [],
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "synthesis_pass": "one-shot",
        },
        "plan": None,
        "logs": [],
        "transcript_preview": "",
        "markdown_preview": markdown_preview,
    }


def list_mp4_runs() -> list[dict]:
    """Discover local MP4 pipeline outputs from Markdowns/TTS_MMDD_*.md files."""
    # Match TTS_MMDD_name.md (4-digit date prefix) but exclude stream replays
    mp4_mds = [
        p for p in MARKDOWNS_DIR.glob("TTS_[0-9][0-9][0-9][0-9]_*.md")
        if "stream" not in p.stem
    ]
    mp4_mds = sorted(mp4_mds, key=lambda p: p.stat().st_mtime, reverse=True)
    return [run_from_mp4_md(p, include_detail=False) for p in mp4_mds[:20]]


def list_runs() -> list[dict]:
    qc_files = [
        path
        for path in RUNS_DIR.glob("*.final-qc.json")
        if ".review-" not in path.name
    ]
    qc_files = sorted(qc_files, key=lambda path: path.stat().st_mtime, reverse=True)
    created = [record_to_run(record, include_detail=False) for record in list_registry_records()]
    # Registry runs take precedence: skip QC-backed runs that share the same base.
    registered_bases = {r["base"] for r in created}
    completed = [
        run_from_qc(path, include_detail=False)
        for path in qc_files[:30]
        if parse_qc_path(path)[0] not in registered_bases
    ]
    # MP4 local pipeline runs (no QC file, discovered from Markdowns/*.md)
    qc_bases = {parse_qc_path(p)[0] for p in qc_files}
    mp4 = [
        r for r in list_mp4_runs()
        if r["base"] not in registered_bases and r["id"] not in qc_bases
    ]
    return (created + completed + mp4)[:50]


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
    with _REGISTRY_LOCK:
        records = [item for item in list_registry_records() if item.get("id") != record.get("id")]
        records.insert(0, record)
        write_json(REGISTRY_PATH, {"version": 1, "records": records[:100]})


def find_registry_record(run_id: str) -> dict | None:
    normalized = run_id.removeprefix("web:")
    for record in list_registry_records():
        if record.get("id") == normalized or f"web:{record.get('id')}" == run_id:
            return record
    return None


def update_registry_record(run_id: str, status: str, log_message: str, level: str = "info") -> dict | None:
    """Update status + append a log entry for a registry run. Returns updated record or None."""
    normalized = run_id.removeprefix("web:")
    records = list_registry_records()
    updated = None
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for record in records:
        if record.get("id") == normalized:
            record["status"] = status
            record["updated_at"] = now
            record.setdefault("logs", []).append({"time": now, "level": level, "message": log_message})
            updated = record
            break
    if updated:
        with _REGISTRY_LOCK:
            write_json(REGISTRY_PATH, {"version": 1, "records": records[:100]})
    return updated


# Non-terminal statuses — frontend should poll these
RUNNING_STATUSES = {"created", "probing", "recording", "transcribing", "synthesizing"}

_SIMULATION_STEPS: list[tuple[str, str, float]] = [
    ("probing",      "Probing source URL and checking auth state...",        3.0),
    ("recording",    "Playwright keepalive started. Capturing live stream.", 5.0),
    ("transcribing", "SenseVoice ASR running on chunk segments.",            6.0),
    ("synthesizing", "Synthesis started. Calling Gemini / Qwen.",            5.0),
    ("completed",    "Pipeline finished. Final QC written.",                 0.0),
]


def simulate_pipeline(run_id: str) -> None:
    """Background thread: advances a created run through the state machine with realistic delays."""
    import time
    for status, message, delay in _SIMULATION_STEPS:
        update_registry_record(run_id, status, message)
        if delay > 0:
            time.sleep(delay)


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
        if not source.startswith("http"):
            warnings.append("Replay 来源看起来不是有效 URL；请粘贴知乎回放视频的完整 https 链接。")
        base = safe_base(str(payload.get("base") or ""), f"replay-{stamp}")
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

    def send_image(self, data: bytes, mime: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/frames":
            from urllib.parse import parse_qs
            params = parse_qs(parsed.query)
            img_rel = unquote(params.get("p", [""])[0])
            if not img_rel:
                self.send_json({"error": "missing ?p= parameter"}, status=400)
                return
            if Path(img_rel).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                self.send_json({"error": "not an image file"}, status=400)
                return
            img_file = _locate_frame_file(img_rel)
            if img_file is None:
                self.send_json({"error": "image not found"}, status=404)
                return
            mime = "image/jpeg" if img_file.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            self.send_image(img_file.read_bytes(), mime)
            return

        if path == "/api/runs":
            self.send_json(list_runs())
            return
        if path == "/api/config":
            self.send_json({
                "running_statuses": list(RUNNING_STATUSES),
                "launch_mode": _LAUNCH_MODE,
                "readonly": _READONLY,
            })
            return
        if path.startswith("/api/runs/"):
            # /api/runs/{id}/live-chunks  — chunks visible during recording before manifest exists
            if path.endswith("/live-chunks"):
                run_id = path.removeprefix("/api/runs/").removesuffix("/live-chunks")
                record = find_registry_record(run_id)
                base = (record.get("plan") or {}).get("base") if record else None
                if not base:
                    # Try to find the base from a QC file (run already completed)
                    qc_path = find_qc_by_id(run_id)
                    base = parse_qc_path(qc_path)[0] if qc_path else None
                if not base:
                    self.send_json({"error": "run not found or base unknown"}, status=404)
                    return
                chunks = chunks_for_base(base, manifest_path=None)
                self.send_json({
                    "base": base,
                    "chunk_count": len(chunks),
                    "chunks": chunks,
                })
                return

            run_id = path.removeprefix("/api/runs/")
            registry_record = find_registry_record(run_id)
            if registry_record:
                self.send_json(record_to_run(registry_record, include_detail=True))
                return
            qc_path = find_qc_by_id(run_id)
            if qc_path:
                self.send_json(run_from_qc(qc_path, include_detail=True))
                return
            # Try MP4 run (id == Markdown stem, e.g. "TTS_0602_MyVideo")
            mp4_md = MARKDOWNS_DIR / f"{run_id}.md"
            if mp4_md.exists():
                self.send_json(run_from_mp4_md(mp4_md, include_detail=True))
                return
            self.send_json({"error": "run not found"}, status=404)
            return
        self.send_json({"error": "not found"}, status=404)

    def do_PATCH(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/runs/"):
            run_id = path.removeprefix("/api/runs/")
            body = self.read_json_body()
            new_status = str(body.get("status") or "").strip()
            message = str(body.get("message") or "").strip()
            level = str(body.get("level") or "info").strip()
            if not new_status:
                self.send_json({"error": "status is required"}, status=400)
                return
            updated = update_registry_record(run_id, new_status, message or f"Status changed to {new_status}.", level)
            if not updated:
                self.send_json({"error": "registry run not found"}, status=404)
                return
            self.send_json(record_to_run(updated, include_detail=True))
            return
        self.send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        import threading
        if _READONLY:
            self.send_json({"error": "server is in read-only mode"}, status=403)
            return
        path = unquote(urlparse(self.path).path)
        if path == "/api/run-plans":
            self.send_json(build_run_plan(self.read_json_body()))
            return
        if path == "/api/runs":
            self.send_json(create_registry_record(self.read_json_body()), status=201)
            return
        if path.startswith("/api/runs/") and path.endswith("/launch"):
            run_id = path.removeprefix("/api/runs/").removesuffix("/launch")
            record = find_registry_record(run_id)
            if not record:
                self.send_json({"error": "registry run not found"}, status=404)
                return
            if record.get("status") not in ("created",):
                self.send_json({"error": f"cannot launch run in status '{record.get('status')}'"}, status=409)
                return
            source_type = (record.get("plan") or {}).get("source_type") or "live"
            if _LAUNCH_MODE == "live":
                launcher = {
                    "live":   launch_live_pipeline,
                    "replay": launch_replay_pipeline,
                    "mp4":    launch_mp4_pipeline,
                }.get(source_type, launch_live_pipeline)
            else:
                launcher = simulate_pipeline  # type: ignore[assignment]
            threading.Thread(target=launcher, args=(run_id, record) if _LAUNCH_MODE == "live" else (run_id,), daemon=True).start()
            self.send_json(record_to_run(record, include_detail=True))
            return
        self.send_json({"error": "not found"}, status=404)


def _find_python() -> str:
    """Return the Python executable to use for subprocess launches on WIN."""
    venv = ROOT.parent / "zhihu_file" / ".venv-sensevoice" / "Scripts" / "python.exe"
    if venv.exists():
        return str(venv)
    venv2 = ROOT / ".venv-sensevoice" / "Scripts" / "python.exe"
    if venv2.exists():
        return str(venv2)
    return sys.executable


def _remove_registry_record(run_id: str) -> None:
    """Delete a registry record so the real QC artifact takes over in list_runs()."""
    normalized = run_id.removeprefix("web:")
    with _REGISTRY_LOCK:
        records = [r for r in list_registry_records() if r.get("id") != normalized]
        write_json(REGISTRY_PATH, {"version": 1, "records": records[:100]})


def _cleanup_orphaned_records(new_url: str) -> None:
    """Remove old failed/created records with the same source URL.

    Prevents stale 'failed' records from piling up when the user retries
    the same URL after a launch error.
    """
    normalized_url = new_url.strip().rstrip("/")
    if not normalized_url:
        return
    with _REGISTRY_LOCK:
        records = list_registry_records()
        keep = []
        removed = 0
        for r in records:
            old_url = str((r.get("plan") or {}).get("source") or "").strip().rstrip("/")
            if old_url and old_url == normalized_url and r.get("status") in ("failed", "created"):
                removed += 1
                continue
            keep.append(r)
        if removed:
            write_json(REGISTRY_PATH, {"version": 1, "records": keep[:100]})


# Keywords detected in subprocess stdout that trigger status transitions.
# Each entry: (status_to_set, list_of_trigger_substrings)
_LIVE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("recording",     ["Input extractor", "HLS Continuous", "Chunk", "Recorder", "Session", "[Recorder]"]),
    ("transcribing",  ["merge_stream_chunks", "合并", "Sections:", "Merging"]),
    ("synthesizing",  ["build_stream_markdown", "NotebookLM", "Sending to", "Gemini", "Qwen"]),
]
_MP4_KEYWORDS: list[tuple[str, list[str]]] = [
    ("recording",     ["Transcribing", "SenseVoice", "Whisper", "extract_keyframes", "Processing"]),
    ("synthesizing",  ["Gemini", "Qwen", "build_final_markdown", "Markdown"]),
]
_REPLAY_KEYWORDS = _LIVE_KEYWORDS  # Same output format as live stream pipeline


def _run_pipeline_engine(
    run_id: str,
    cmd: list[str],
    env: dict | None,
    keywords: list[tuple[str, list[str]]],
    log_every_n: int = 15,
) -> bool:
    """Run a subprocess, parse stdout for status transitions, write log entries.

    Returns True on clean exit (returncode==0), False on failure.
    """
    import subprocess

    current_status = "recording"
    triggered: set[str] = set()
    line_buf: list[str] = []

    def _flush_log(lines: list[str], force: bool = False) -> None:
        """Write accumulated lines as a single log entry."""
        if not lines:
            return
        msg = " | ".join(l[:120] for l in lines[-5:])  # keep last 5 lines of buffer
        update_registry_record(run_id, current_status, msg)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env or os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        update_registry_record(run_id, "recording", f"Process started (PID {proc.pid})")

        for raw_line in proc.stdout:
            # Aggressively strip ANSI/control characters from subprocess output
            line = raw_line
            # Remove ANSI escape sequences (\x1b[...m, \x1b[K, etc.)
            line = _ANSI_RE.sub("", line)
            # Remove all control characters except newline and tab
            line = "".join(ch for ch in line if ch.isprintable() or ch in "\n\t")
            line = line.strip()
            if not line:
                continue
            line_buf.append(line)

            # Status transition detection
            for new_status, triggers in keywords:
                if new_status not in triggered and any(t in line for t in triggers):
                    triggered.add(new_status)
                    current_status = new_status
                    update_registry_record(run_id, new_status, line[:120])

            # Periodic log flush
            if len(line_buf) >= log_every_n:
                _flush_log(line_buf)
                line_buf = []

        proc.wait()
        _flush_log(line_buf, force=True)

        if proc.returncode == 0:
            return True
        update_registry_record(run_id, "failed",
                               f"Process exited with code {proc.returncode}.", "error")
        return False

    except Exception as exc:
        update_registry_record(run_id, "failed", f"Launch error: {exc}", "error")
        return False


def _resolve_run_base(hint: str) -> str:
    """Find the actual base name used by the capture pipeline.

    The pipeline applies safe_name() sanitisation, so look for checkpoint
    or chunk files matching the hint prefix.
    """
    for pattern in (f"stream-{hint}_chunk*.md", f"stream-{hint}.checkpoint.json"):
        candidates = sorted(RUNS_DIR.glob(pattern))
        if candidates:
            # Extract base from chunk filename: stream-<base>_chunk001_0s-...
            name = candidates[0].name
            # Remove leading "stream-" and trailing "_chunk..." or ".checkpoint..."
            name = name[len("stream-"):]
            idx = name.find("_chunk")
            if idx < 0:
                idx = name.find(".checkpoint")
            if idx > 0:
                return name[:idx]
            return name
    return hint


def launch_live_pipeline(run_id: str, record: dict) -> None:
    """WIN-only: live capture via playwright-keepalive → merge → synthesis."""
    plan = record.get("plan") or {}
    source = str(plan.get("source") or "").strip()
    base = str(plan.get("base") or "").strip()
    provider = str(plan.get("provider") or "gemini")
    synthesis_pass = str(plan.get("synthesis_pass") or "one-shot")
    if not source:
        update_registry_record(run_id, "failed", "No source URL in plan.", "error")
        return

    # Remove stale failed records for the same URL (from previous retries)
    _cleanup_orphaned_records(source)

    python = _find_python()
    auth = ROOT / "zhihu_auth_state.json"
    if not auth.exists():
        update_registry_record(run_id, "failed", "zhihu_auth_state.json not found.", "error")
        return

    # Step 1: live capture — --duration 0 means run until stream ends
    captured_name = base or f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    capture_cmd = [
        python, "-u", str(ROOT / "zhihuTTS_stream.py"),
        "--playwright-keepalive",
        "--page-url", source,
        "--playwright-storage-state", str(auth),
        "--playwright-save-storage-state", str(auth),
        "--duration", "0",
        "--chunk-duration", "60",
        "--name", captured_name,
    ]

    update_registry_record(run_id, "probing", f"Starting live capture: {source[:80]}")
    ok = _run_pipeline_engine(run_id, capture_cmd, None, _LIVE_KEYWORDS)
    if not ok:
        return

    # Resolve actual base name from runs directory
    resolved = _resolve_run_base(captured_name)
    if not resolved:
        resolved = captured_name

    # Step 2: merge
    update_registry_record(run_id, "transcribing", "Merging stream chunks…")
    merge_cmd = [
        python, str(ROOT / "scripts" / "merge_stream_chunks.py"),
        "--base", resolved,
        "--runs-dir", str(RUNS_DIR),
    ]
    ok = _run_pipeline_engine(run_id, merge_cmd, None, [])
    if not ok:
        return

    # Step 3: synthesis
    update_registry_record(run_id, "synthesizing", "Building NotebookLM document…")
    synth_cmd = [
        python, str(ROOT / "scripts" / "build_stream_markdown.py"),
        "--base", resolved,
        "--runs-dir", str(RUNS_DIR),
        "--markdowns-dir", str(MARKDOWNS_DIR),
        "--provider", provider,
        "--synthesis-pass", synthesis_pass,
        "--output-label", provider,
    ]
    if provider == "qwen":
        synth_cmd += ["--qwen-max-frames", "250"]
    ok = _run_pipeline_engine(run_id, synth_cmd, None, [])
    if ok:
        update_registry_record(run_id, "completed", "Live pipeline finished. Refreshing index…")
        _remove_registry_record(run_id)


def launch_replay_pipeline(run_id: str, record: dict) -> None:
    """WIN-only: capture a replay URL then run Qwen synthesis."""
    import subprocess
    plan = record.get("plan") or {}
    source = str(plan.get("source") or "").strip()
    base = str(plan.get("base") or "").strip()
    provider = str(plan.get("provider") or "qwen")
    synthesis_pass = str(plan.get("synthesis_pass") or "sliding-window")
    qwen_max_frames = int(plan.get("qwen_max_frames") or 250)
    if not source:
        update_registry_record(run_id, "failed", "No source URL in plan.", "error")
        return

    python = _find_python()
    update_registry_record(run_id, "probing", f"Starting replay capture: {source[:80]}")

    # Step 1: capture replay
    # zhihu.com pages need Playwright to extract the media stream.
    # Direct media URLs (mp4/m3u8/flv) can be probed by ffmpeg directly.
    is_page_url = any(domain in source for domain in ("zhihu.com", "xet.pomoho.com"))
    if is_page_url:
        auth_file = ROOT / "zhihu_auth_state.json"
        capture_cmd = [
            python, str(ROOT / "zhihuTTS_stream.py"),
            "--page-url", source,
            "--extractor", "playwright",
            "--chunk-duration", "60",
            "--name", base,
            "--cleanup-slices",
        ]
        if auth_file.exists():
            capture_cmd += ["--playwright-storage-state", str(auth_file)]
    else:
        capture_cmd = [
            python, str(ROOT / "zhihuTTS_stream.py"),
            "--url", source,
            "--chunk-duration", "60",
            "--name", base,
            "--cleanup-slices",
        ]
    ok = _run_pipeline_engine(run_id, capture_cmd, None, _REPLAY_KEYWORDS)
    if not ok:
        return

    # Step 2: synthesis
    update_registry_record(run_id, "synthesizing", "Capture done. Starting synthesis…")
    synth_cmd = [
        python, str(ROOT / "scripts" / "build_stream_markdown.py"),
        "--base", base,
        "--runs-dir", str(ROOT / "runs"),
        "--markdowns-dir", str(ROOT / "Markdowns"),
        "--provider", provider,
        "--synthesis-pass", synthesis_pass,
        "--qwen-max-frames", str(qwen_max_frames),
        "--output-label", provider,
    ]
    ok2 = _run_pipeline_engine(run_id, synth_cmd, None, [])
    if ok2:
        update_registry_record(run_id, "completed", "Replay pipeline finished. Refreshing index…")
        _remove_registry_record(run_id)


def launch_mp4_pipeline(run_id: str, record: dict) -> None:
    """WIN-only: process a local MP4 file through run_single_file.py."""
    plan = record.get("plan") or {}
    source = str(plan.get("source") or "").strip()
    if not source:
        update_registry_record(run_id, "failed", "No file path in plan.", "error")
        return
    python = _find_python()
    update_registry_record(run_id, "probing", f"Launching MP4 pipeline: {source[:80]}")
    cmd = [python, str(ROOT / "run_single_file.py"), source]
    ok = _run_pipeline_engine(run_id, cmd, None, _MP4_KEYWORDS)
    if ok:
        update_registry_record(run_id, "completed", "MP4 pipeline finished. Refreshing index…")
        _remove_registry_record(run_id)


def main() -> None:
    global _READONLY, _LAUNCH_MODE
    parser = argparse.ArgumentParser(description="zhihu web API server")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address. Use 0.0.0.0 to allow network access from MAC.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--readonly", action="store_true",
                        help="Disable POST/PATCH. Useful when MAC runs a local viewer instance.")
    parser.add_argument("--launch-mode", choices=["simulate", "live"], default="simulate",
                        help="simulate: background thread state machine (default). "
                             "live: calls run_zhihu_live.bat via subprocess (WIN only).")
    args = parser.parse_args()
    _READONLY = args.readonly
    _LAUNCH_MODE = args.launch_mode

    mode_tag = "[READ-ONLY]" if _READONLY else f"[{_LAUNCH_MODE.upper()} launch]"
    print(f"zhihu web_api {mode_tag}  listening on http://{args.host}:{args.port}")
    print(f"  project root : {ROOT}")
    print(f"  runs dir     : {RUNS_DIR}")
    if args.host != "127.0.0.1":
        import socket
        try:
            lan_ip = socket.gethostbyname(socket.gethostname())
            print(f"  MAC can connect via: http://{lan_ip}:{args.port}")
        except Exception:
            pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

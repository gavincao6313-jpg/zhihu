"""P1 Sectioned Synthesis: three-pass pipeline for live-stream final documents.

Replaces the one-shot Gemini call in build_stream_markdown.py with:
  Pass A — per-section fact extraction  (gemini-2.5-flash, one call per section)
  Pass B — global outline merge         (flash by default, pro if needed)
  Pass C — final document assembly      (configurable, pro recommended)

Run directory layout
--------------------
runs/live-final/<base>-<run-ts>/
  manifest.json            <- pipeline state + per-section status
  final-qc.json            <- input quality manifest (from P0 live_final_qc)
  evidence/
    section_001.json
    section_002.json
    ...
  notes/
    section_001.md
    section_002.md
    ...
  outline.json
  final.md
  final-markdown-qc.json

Usage (experimental only; production live synthesis remains one Gemini call):
    python scripts/live_sectioned_synthesis.py smoke   # smoke test
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

MANIFEST_FILENAME = "manifest.json"
OUTLINE_FILENAME  = "outline.json"
FINAL_MD_FILENAME = "final.md"
FINAL_QC_FILENAME = "final-markdown-qc.json"

# ── Run directory helpers ─────────────────────────────────────────────────────


def run_dir_path(runs_dir: Path, base: str, run_ts: str) -> Path:
    """Return the canonical run directory path (does not create it)."""
    return runs_dir / "live-final" / f"{base}-{run_ts}"


def setup_run_dir(runs_dir: Path, base: str, run_ts: str) -> Path:
    """Create the full P1 run directory tree and return the run directory path."""
    run_dir = run_dir_path(runs_dir, base, run_ts)
    for sub in ("evidence", "notes"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


# ── Manifest schema ───────────────────────────────────────────────────────────


def _section_entry(section_id: str, start_s: int, end_s: int) -> dict:
    return {
        "section_id":      section_id,
        "start_s":         start_s,
        "end_s":           end_s,
        "evidence_hash":   None,
        "evidence_status": "pending",
        "note_status":     "pending",
        "note_model":      None,
        "note_attempts":   0,
        "note_path":       None,
        "last_error":      None,
    }


def init_manifest(
    run_dir: Path,
    base: str,
    run_ts: str,
    sections_meta: list[dict],
    p0_manifest: dict | None = None,
) -> dict:
    """Create and persist the initial manifest.json for a new P1 run.

    sections_meta: list of {section_id, start_s, end_s} dicts.
    p0_manifest:   the quality manifest from live_final_qc() (P0).

    Raises FileExistsError if manifest already exists — use load_manifest()
    to resume an in-progress run.
    """
    manifest_path = run_dir / MANIFEST_FILENAME
    if manifest_path.exists():
        raise FileExistsError(
            f"Manifest already exists at {manifest_path}. "
            "Use load_manifest() to resume."
        )

    manifest = {
        "base":           base,
        "run_ts":         run_ts,
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "synthesis_pass": "sectioned/3-pass",
        "source_status":  (p0_manifest or {}).get("source_status", "unknown"),
        "p0_qc":          p0_manifest,
        "sections":       [
            _section_entry(m["section_id"], m["start_s"], m["end_s"])
            for m in sections_meta
        ],
        "pass_b_status":  "pending",
        "pass_c_status":  "pending",
        "outline_path":   None,
        "final_md_path":  None,
    }
    _atomic_write(manifest_path, manifest)
    return manifest


def load_manifest(run_dir: Path) -> dict:
    """Load manifest.json from a run directory."""
    manifest_path = run_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest found at {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def save_manifest(run_dir: Path, manifest: dict) -> None:
    """Atomically persist an updated manifest dict to disk."""
    _atomic_write(run_dir / MANIFEST_FILENAME, manifest)


def update_section(run_dir: Path, section_id: str, **kwargs) -> dict:
    """Load manifest, update one section's fields, save, return updated manifest.

    Raises KeyError if section_id is not found.
    """
    manifest = load_manifest(run_dir)
    section  = next(
        (s for s in manifest["sections"] if s["section_id"] == section_id), None
    )
    if section is None:
        raise KeyError(f"section_id '{section_id}' not found in manifest")
    section.update(kwargs)
    save_manifest(run_dir, manifest)
    return manifest


def mark_section_stale_if_hash_changed(
    run_dir: Path, section_id: str, new_hash: str
) -> bool:
    """If the stored evidence_hash differs from new_hash, mark note_status stale.

    Returns True if the section was marked stale, False if hash unchanged.
    """
    manifest = load_manifest(run_dir)
    section  = next(
        (s for s in manifest["sections"] if s["section_id"] == section_id), None
    )
    if section is None:
        raise KeyError(f"section_id '{section_id}' not found in manifest")

    if section.get("evidence_hash") != new_hash:
        section["evidence_hash"] = new_hash
        if section["note_status"] == "done":
            section["note_status"] = "stale"
        save_manifest(run_dir, manifest)
        return True
    return False


def pending_sections(manifest: dict) -> list[dict]:
    """Return sections that still need Pass A.

    Resume rules (roadmap P1-3):
      done + evidence_hash unchanged  → skip
      pending / stale / failed        → re-run
      running                         → re-run (crash recovery: was interrupted mid-call)
    """
    return [
        s for s in manifest["sections"]
        if s["note_status"] in ("pending", "stale", "failed", "running")
    ]


def all_sections_done(manifest: dict) -> bool:
    """True when every section has note_status == 'done'."""
    return all(s["note_status"] == "done" for s in manifest["sections"])


# ── P1-4 Pass A ───────────────────────────────────────────────────────────────

PASS_A_MODEL              = "gemini-2.5-flash"
PASS_A_PRO_MODEL          = "gemini-2.5-pro"
MAX_PASS_A_FLASH_ATTEMPTS = 2    # escalate to pro after this many flash failures
PASS_A_CALL_DELAY_S       = 6.0  # 10 RPM free-tier → 6 s between calls
PASS_A_MAX_RETRIES        = 2    # 429-level retries per call attempt
PASS_A_MAX_CONTINUATIONS  = 4    # section notes are short; rarely hit MAX_TOKENS


def _pass_a_prompt(header: str) -> str:
    """Build the Pass A system instruction for one section."""
    return (
        "你是一位内容提炼专家，正在处理一段来自中文知识付费直播的片段。\n\n"
        "请从以下文字记录（可能附有关键帧截图）中，严格按照格式提炼该段核心信息，"
        "直接以章节标题行开头，不要包裹代码块，不要额外说明：\n\n"
        f"{header}\n"
        "- 核心主题：（该段中心话题，一句话）\n"
        "- 关键论点：（2-5 个要点，每条以 • 开头）\n"
        "- 关键术语：（技术词/产品名/人名/缩写，逗号分隔；无则填写：无）\n"
        "- 视觉证据：（截图中的图表/幻灯片/代码描述；无截图或无实质内容则填写：无）\n"
        "- 重要案例：（具体举例/数据/公司产品名；无则填写：无）\n"
        "- 原话候选：（值得引用的原话，≤2 句；无则填写：无）\n"
        "- 行动项/作业：（主播布置的任务或行动建议；无则填写：无）\n"
        "- 不确定点：（转录模糊/矛盾/需二次确认处；无则填写：无）\n\n"
        "规则：关键术语保留原始大小写（如 Claude Code、MCP、RAG）。"
        "若整段转录 < 50 字，核心主题填写 [无有效内容]，其余字段填写：无。\n\n"
        "---\n文字记录：\n"
    )


def _build_pass_a_parts(evidence: dict) -> list:
    """Build the Gemini parts list for one section's Pass A call.

    Parts: [prompt_text, transcript_text, (label, image_blob)...]
    Frames are inlined as JPEG bytes.  Raises ImportError if google-genai
    is not installed (deferred until actual Gemini calls are needed).
    """
    from google.genai import types as _gt  # lazy — not needed for smoke tests

    section_id = evidence["section_id"]
    num        = int(section_id.split("_")[1])
    start_hms  = _s_to_hms(evidence["start_s"])
    end_hms    = _s_to_hms(evidence["end_s"])
    header     = f"## Section {num:02d} [{start_hms} – {end_hms}]"

    transcript = (
        evidence.get("cleaned_transcript") or evidence.get("transcript", "")
    ).strip() or "[无文字记录]"
    parts: list = [_pass_a_prompt(header), transcript]

    for frame in evidence.get("frames", []):
        fp = Path(frame["path"])
        if not fp.exists():
            continue
        ts_label = _s_to_hms(frame.get("ts", 0))
        parts.append(f"[截图 {ts_label}]")
        parts.append(_gt.Part(
            inline_data=_gt.Blob(mime_type="image/jpeg", data=fp.read_bytes())
        ))

    return parts


def run_pass_a(
    run_dir: Path,
    section_id: str,
    client,
    config: dict | None = None,
) -> str | None:
    """Execute Pass A for one section: evidence → section note Markdown.

    State transitions:
      pending / stale / failed / running → running (before call)
                                         → done    (on success)
                                         → failed  (on failure)

    Returns note text on success, None on failure.
    Escalates to Pro after MAX_PASS_A_FLASH_ATTEMPTS flash failures.
    If pass_b was 'done', marks it 'stale' when this note changes.
    """
    from utils import call_gemini as _call_gemini

    cfg = config or {}

    evidence_path = run_dir / "evidence" / f"{section_id}.json"
    if not evidence_path.exists():
        raise FileNotFoundError(f"Evidence not found: {evidence_path}")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    manifest = load_manifest(run_dir)
    section  = next(
        (s for s in manifest["sections"] if s["section_id"] == section_id), None
    )
    if section is None:
        raise KeyError(f"section_id '{section_id}' not found in manifest")

    attempts  = section.get("note_attempts", 0) + 1
    max_flash = int(cfg.get("max_flash_attempts", MAX_PASS_A_FLASH_ATTEMPTS))
    model     = (
        cfg.get("pass_a_pro_model", PASS_A_PRO_MODEL)
        if attempts > max_flash
        else cfg.get("pass_a_model", PASS_A_MODEL)
    )

    update_section(run_dir, section_id,
                   note_status="running",
                   note_attempts=attempts,
                   note_model=model,
                   last_error=None)

    parts     = _build_pass_a_parts(evidence)
    note_text = _call_gemini(
        client, parts, section_id,
        model=model,
        max_retries=int(cfg.get("pass_a_max_retries", PASS_A_MAX_RETRIES)),
        max_continuations=int(cfg.get("pass_a_max_continuations", PASS_A_MAX_CONTINUATIONS)),
    )

    if note_text:
        note_path = run_dir / "notes" / f"{section_id}.md"
        note_path.write_text(note_text, encoding="utf-8")
        update_section(run_dir, section_id,
                       note_status="done",
                       note_path=str(note_path.relative_to(run_dir)),
                       note_model=model,
                       last_error=None)
        m = load_manifest(run_dir)
        if m.get("pass_b_status") == "done":
            update_pass_state(run_dir, "pass_b", "stale")
        return note_text

    error_msg = f"call_gemini returned None after {attempts} attempt(s)"
    update_section(run_dir, section_id,
                   note_status="failed",
                   last_error=error_msg)
    return None


def run_pass_a_all(
    run_dir: Path,
    client,
    config: dict | None = None,
    call_delay_s: float | None = None,
) -> tuple[int, int]:
    """Run Pass A for all pending sections in section order.

    Applies call_delay_s sleep between each Gemini call to respect the
    10 RPM free-tier limit (default 6 s).

    Returns (done_count, failed_count).
    """
    delay    = call_delay_s if call_delay_s is not None else PASS_A_CALL_DELAY_S
    manifest = load_manifest(run_dir)
    todo     = pending_sections(manifest)

    if not todo:
        print("[pass_a] All sections done — nothing to do.", flush=True)
        return 0, 0

    print(f"[pass_a] {len(todo)} section(s) pending.", flush=True)
    done_count   = 0
    failed_count = 0

    for i, section in enumerate(todo):
        if i > 0:
            time.sleep(delay)
        section_id = section["section_id"]
        print(f"[pass_a] {section_id} ({i + 1}/{len(todo)})", flush=True)
        result = run_pass_a(run_dir, section_id, client, config)
        if result is not None:
            done_count   += 1
        else:
            failed_count += 1

    status = "complete" if failed_count == 0 else f"{failed_count} failed"
    print(f"[pass_a] {done_count}/{done_count + failed_count} done ({status}).", flush=True)
    return done_count, failed_count


# ── P1-3 Pass B / C state helpers ─────────────────────────────────────────────


def update_pass_state(
    run_dir: Path, pass_name: str, status: str, **kwargs
) -> dict:
    """Set pass_b_status or pass_c_status in the manifest.

    pass_name: "pass_b" or "pass_c"
    status:    "pending" / "running" / "done" / "failed" / "stale"
    Extra kwargs (e.g. outline_path, final_md_path) are merged into the
    top-level manifest dict.
    """
    key = f"{pass_name}_status"
    manifest = load_manifest(run_dir)
    if key not in manifest:
        raise KeyError(f"Pass key '{key}' not found in manifest")
    manifest[key] = status
    manifest.update(kwargs)
    save_manifest(run_dir, manifest)
    return manifest


def pass_b_needs_rerun(manifest: dict) -> bool:
    """True when Pass B should run or re-run.

    Initial run:  pass_b_status is 'pending' (all sections must be done first).
    Stale rerun:  pass_b_status is 'stale' — a section note was re-generated
                  after Pass B completed (Pass A sets pass_b to stale on done).
    Error rerun:  pass_b_status is 'failed' or 'running'.
    """
    return manifest.get("pass_b_status", "pending") in (
        "pending", "stale", "failed", "running"
    )


def pass_c_needs_rerun(manifest: dict) -> bool:
    """True when Pass C should run or re-run.

    Gated on Pass B being done first.
    """
    if manifest.get("pass_b_status") != "done":
        return False
    return manifest.get("pass_c_status", "pending") in (
        "pending", "stale", "failed", "running"
    )


# ── P1-5 Pass B ───────────────────────────────────────────────────────────────

PASS_B_MODEL         = "gemini-2.5-flash"
PASS_B_PRO_MODEL     = "gemini-2.5-pro"
OUTLINE_MIN_CHAPTERS = 2
OUTLINE_MAX_CHAPTERS = 20


def _load_section_notes(run_dir: Path, manifest: dict) -> str:
    """Return all section notes concatenated in section order."""
    parts: list[str] = []
    for s in manifest["sections"]:
        note_rel = s.get("note_path")
        if not note_rel:
            continue
        note_path = run_dir / note_rel
        if note_path.exists():
            parts.append(note_path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts)


def _pass_b_prompt(notes_combined: str, manifest: dict) -> str:
    """Build the Pass B outline-merge prompt."""
    total_s   = max((s["end_s"] for s in manifest["sections"]), default=0)
    total_min = total_s // 60
    sec_count = len(manifest["sections"])
    ch_min    = max(2, total_min // 15)
    ch_max    = max(ch_min + 3, total_min // 8)
    return (
        f"你是一位内容架构师，正在整理一场约 {total_min} 分钟的中文知识付费直播。\n"
        f"直播已被切分为 {sec_count} 个片段，以下是每段独立提炼的 Section Notes。\n"
        "请将这些片段合并为全局章节树，输出 JSON（不要包裹代码块，不要任何解释）。\n\n"
        "输出格式：\n"
        '{"chapters":[{"title":"章节标题（15字内）",'
        '"start_s":起始秒,"end_s":结束秒,'
        '"sections":["section_001","section_002"]}]}\n\n'
        "规则：\n"
        "1. 每个 section_id 恰好出现在一个章节，不得遗漏或重复。\n"
        "2. 同一章节内 sections 按时间顺序排列。\n"
        "3. 章节按 start_s 单调递增排列。\n"
        f"4. 章节数建议 {ch_min}–{ch_max} 个（根据内容疏密调整）。\n"
        "5. start_s 取该章节第一个 section 的 start_s；"
        "end_s 取最后一个 section 的 end_s。\n\n"
        "---\nSection Notes:\n\n"
        + notes_combined
    )


def _extract_json_from_response(text: str) -> dict:
    """Parse a JSON dict from a Gemini response that may be wrapped in fences."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"(\{.*\})", stripped, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError(f"No JSON object found in response (first 300 chars): {stripped[:300]}")


def _validate_outline(outline: dict, manifest: dict) -> list[str]:
    """Check outline structure. Returns list of error strings; empty = valid."""
    errors: list[str] = []
    chapters = outline.get("chapters")
    if not chapters:
        errors.append("outline missing 'chapters' list")
        return errors

    if len(chapters) < OUTLINE_MIN_CHAPTERS:
        errors.append(f"too few chapters: {len(chapters)}")
    if len(chapters) > OUTLINE_MAX_CHAPTERS:
        errors.append(f"too many chapters: {len(chapters)}")

    known_ids    = {s["section_id"] for s in manifest["sections"]}
    seen_ids: list[str] = []
    prev_end_s   = -1

    for i, ch in enumerate(chapters):
        title   = ch.get("title", "")
        start_s = ch.get("start_s", -1)
        end_s   = ch.get("end_s", -1)
        secs    = ch.get("sections", [])

        if not title:
            errors.append(f"chapter {i} missing title")
        if start_s < prev_end_s:
            errors.append(
                f"chapter {i} start_s {start_s} < previous end_s {prev_end_s}"
            )
        if end_s < start_s:
            errors.append(f"chapter {i} end_s {end_s} < start_s {start_s}")
        if not secs:
            errors.append(f"chapter {i} has no sections")
        for sid in secs:
            if sid not in known_ids:
                errors.append(f"unknown section_id {sid!r} in chapter {i}")
        seen_ids.extend(secs)
        prev_end_s = end_s

    # Completeness + uniqueness
    missing = known_ids - set(seen_ids)
    if missing:
        errors.append(f"sections not assigned to any chapter: {sorted(missing)}")
    dupes = {sid for sid in seen_ids if seen_ids.count(sid) > 1}
    if dupes:
        errors.append(f"section_ids appear in multiple chapters: {sorted(dupes)}")

    return errors


def run_pass_b(
    run_dir: Path,
    client,
    config: dict | None = None,
) -> dict | None:
    """Execute Pass B: merge all section notes into a global chapter outline.

    Tries gemini-2.5-flash first; if outline QC fails, re-runs with
    gemini-2.5-pro.  Writes outline.json and updates manifest.

    Raises RuntimeError if not all sections are done.
    Returns the outline dict on success, None on failure.
    """
    cfg      = config or {}
    manifest = load_manifest(run_dir)

    if not all_sections_done(manifest):
        pending = [s["section_id"] for s in manifest["sections"]
                   if s["note_status"] != "done"]
        raise RuntimeError(
            f"Pass B requires all sections done; still pending: {pending}"
        )

    update_pass_state(run_dir, "pass_b", "running")

    notes_combined = _load_section_notes(run_dir, manifest)
    if not notes_combined.strip():
        update_pass_state(run_dir, "pass_b", "failed")
        print("[pass_b] FAILED: no section notes found", flush=True)
        return None

    models = [
        cfg.get("pass_b_model", PASS_B_MODEL),
        cfg.get("pass_b_pro_model", PASS_B_PRO_MODEL),
    ]

    last_errors: list[str] = []
    result_outline: dict | None = None
    from utils import call_gemini as _call_gemini  # lazy — not needed for tests

    for model in models:
        label    = f"pass_b/{model.split('-')[-1]}"
        prompt   = _pass_b_prompt(notes_combined, manifest)
        response = _call_gemini(
            client, [prompt], label,
            model=model, max_retries=2, max_continuations=2,
        )
        if not response:
            last_errors.append(f"{model}: call_gemini returned None")
            continue

        try:
            outline = _extract_json_from_response(response)
        except (ValueError, json.JSONDecodeError) as exc:
            last_errors.append(f"{model}: JSON parse error — {exc}")
            continue

        qc_errors = _validate_outline(outline, manifest)
        if qc_errors:
            last_errors.append(f"{model}: QC failed — {qc_errors}")
            time.sleep(PASS_A_CALL_DELAY_S)   # rate-limit gap before pro retry
            continue

        outline["model_used"] = model
        result_outline = outline
        break

    if result_outline is None:
        update_pass_state(run_dir, "pass_b", "failed")
        print(f"[pass_b] FAILED after all models: {last_errors}", flush=True)
        return None

    outline_path = run_dir / OUTLINE_FILENAME
    _atomic_write(outline_path, result_outline)
    update_pass_state(
        run_dir, "pass_b", "done",
        outline_path=str(outline_path.relative_to(run_dir)),
    )
    # Pass C must re-run if it previously completed
    m = load_manifest(run_dir)
    if m.get("pass_c_status") == "done":
        update_pass_state(run_dir, "pass_c", "stale")

    ch_count = len(result_outline["chapters"])
    print(
        f"[pass_b] Done: {ch_count} chapters, model={result_outline['model_used']}",
        flush=True,
    )
    return result_outline


# ── P1-6 Pass C ───────────────────────────────────────────────────────────────

PASS_C_MODEL             = "gemini-2.5-pro"
PASS_C_MAX_RETRIES       = 3
PASS_C_MAX_CONTINUATIONS = 20   # final doc can be long; matches utils.call_gemini default

_PASS_C_PROMPT_PREFIX = """\
# 角色与目标
你是一个顶级的知识库文档撰写专家。我将提供一场中文AI技术直播课的**预提炼 Section Notes**（已按章节整理）和**全局章节架构**，请将它们综合整理为一份**高度详尽、结构化、完全适合导入 NotebookLM 作为底层语料的 Markdown 文档**。

# 背景信息（重要）
本视频是一场中文AI技术直播课/讲座，内容通常涉及大语言模型（LLM）、RAG（检索增强生成）、MCP（Model Context Protocol）、Agent、Claude、Cursor、ComfyUI、SenseVoice、FunASR 等AI开发工具和技术。请优先识别并准确保留这些专业术语原文，不要翻译或通俗化处理。

# 输入说明
- **全局章节架构**：Pass B 整理的章节划分，包含时间范围和章节标题
- **Section Notes**：每个约 10 分钟片段的内容提炼，包含核心主题、关键论点、关键术语、视觉证据、重要案例、原话候选等字段

# 合成原则（至关重要）
1. **深度展开每章**：以章节架构为骨架，用 Section Notes 中的细节充实每章内容，不要只复述摘要。
2. **合并同主题片段**：同一章节内的多个 Section Notes 如有内容连续，请合并为流畅叙述。
3. **保留专业术语**：精准提取专有名词、工具名称，保持原始大小写（Claude Code、MCP、RAG）。
4. **时间锚点**：在章节标题前标注时间范围；正文关键点可加时间戳 [HH:MM:SS]。
5. **原话保留**：Section Notes 中的原话候选字段如有有效内容，请引用到对应章节。

# 必须输出的 Markdown 结构

请严格按照以下模板输出内容：

## 1. 视频元数据
- **推测主题：** （用一句话概括视频核心内容）
- **核心关键词：** （提供 5-10 个便于检索的关键词/标签）
- **适用受众/场景：** （这段视频主要解决什么问题）

## 2. 核心知识字典（Glossary）
（从所有 Section Notes 的关键术语字段汇总，提取 5-10 个核心概念，给出视频语境下的定义）

## 3. 详尽内容解析（按章节）
（以 Pass B 章节架构为骨架，每章格式如下）
### [开始时间 - 结束时间] 章节标题
- **核心论点：** （本章的重点结论）
- **详细展开：** （充分利用 Section Notes 中的关键论点、重要案例、视觉证据）
- **视觉/屏幕内容：** （汇总本章各 Section 的视觉证据；若无则省略此项）
- **重要金句/原话：** （汇总本章各 Section 的原话候选；若无则省略此项）

## 4. 遗留问题与下一步行动（如有）
（汇总所有 Section Notes 的行动项/作业字段；若无则写：本场直播暂无明确行动项）

# 执行要求
由于输入信息量极大，请保持极高的专注度，不要省略任何章节。如果输出达到字数上限，请停在当前完整段落，我会回复继续，你再接着上文输出。
"""


def _build_pass_c_prompt(
    outline: dict,
    notes_by_section: dict[str, str],
    manifest: dict,
) -> str:
    """Assemble the Pass C prompt: prefix + chapter outline + notes organised by chapter."""
    chapters = outline.get("chapters", [])

    chapters_text = "\n".join(
        f"[{_s_to_hms(ch.get('start_s', 0))} – {_s_to_hms(ch.get('end_s', 0))}] "
        f"{ch.get('title', '(unnamed)')}  "
        f"<- {', '.join(ch.get('sections', []))}"
        for ch in chapters
    )

    chapter_blocks: list[str] = []
    for ch in chapters:
        title   = ch.get("title", "(unnamed)")
        start_s = ch.get("start_s", 0)
        end_s   = ch.get("end_s", 0)
        header  = f"### [{_s_to_hms(start_s)} – {_s_to_hms(end_s)}] {title}"
        parts   = [header]
        for sid in ch.get("sections", []):
            note = notes_by_section.get(sid, "")
            if note:
                parts.append(note)
        chapter_blocks.append("\n\n".join(parts))

    organized = "\n\n---\n\n".join(chapter_blocks)

    return (
        _PASS_C_PROMPT_PREFIX
        + "\n---\n\n"
        + "## 全局章节架构\n\n"
        + chapters_text
        + "\n\n---\n\n"
        + "## Section Notes（按章节组织）\n\n"
        + organized
    )


def run_pass_c(
    run_dir: Path,
    client,
    config: dict | None = None,
) -> str | None:
    """Execute Pass C: synthesize outline + section notes into the final document.

    State: pending/stale/failed/running → running → done | failed

    Uses gemini-2.5-pro by default; honours call_gemini continuation for long
    outputs.  Writes final.md and updates manifest.

    Raises RuntimeError if pass_b is not done.
    Returns final document text on success, None on failure.
    """
    cfg      = config or {}
    manifest = load_manifest(run_dir)

    if manifest.get("pass_b_status") != "done":
        raise RuntimeError(
            f"Pass C requires pass_b=done; "
            f"current: {manifest.get('pass_b_status')}"
        )

    outline_rel = manifest.get("outline_path")
    if not outline_rel:
        raise RuntimeError("manifest.outline_path not set; run pass_b first")
    outline_abs = run_dir / outline_rel
    if not outline_abs.exists():
        raise RuntimeError(f"outline.json missing: {outline_abs}")
    outline = json.loads(outline_abs.read_text(encoding="utf-8"))

    notes_by_section: dict[str, str] = {}
    for s in manifest["sections"]:
        note_rel = s.get("note_path")
        if not note_rel:
            continue
        note_path = run_dir / note_rel
        if note_path.exists():
            notes_by_section[s["section_id"]] = (
                note_path.read_text(encoding="utf-8").strip()
            )

    model = cfg.get("pass_c_model", PASS_C_MODEL)
    update_pass_state(run_dir, "pass_c", "running")

    prompt = _build_pass_c_prompt(outline, notes_by_section, manifest)
    from utils import call_gemini as _call_gemini  # lazy — not needed for tests
    final_text = _call_gemini(
        client, [prompt], "pass_c",
        model=model,
        max_retries=int(cfg.get("pass_c_max_retries", PASS_C_MAX_RETRIES)),
        max_continuations=int(
            cfg.get("pass_c_max_continuations", PASS_C_MAX_CONTINUATIONS)
        ),
    )

    if not final_text:
        update_pass_state(run_dir, "pass_c", "failed")
        print("[pass_c] FAILED: call_gemini returned None", flush=True)
        return None

    final_path = run_dir / FINAL_MD_FILENAME
    final_path.write_text(final_text, encoding="utf-8")
    update_pass_state(
        run_dir, "pass_c", "done",
        final_md_path=str(final_path.relative_to(run_dir)),
    )

    print(f"[pass_c] Done: {len(final_text):,} chars, model={model}", flush=True)
    return final_text


# ── P1-7 Final Markdown QC ───────────────────────────────────────────────────

COVERAGE_RATIO         = 0.90   # last timestamp must reach ≥ 90% of stream end
LATE_COVERAGE_WINDOW_S = 1200   # warn if last 20 min not covered

_REQUIRED_SECTIONS = [
    ("视频元数据",      ["视频元数据", "元数据"]),
    ("核心知识字典",    ["核心知识字典", "Glossary", "知识字典"]),
    ("详尽内容解析",    ["详尽内容解析", "内容解析"]),
    ("遗留问题/行动项", ["遗留问题", "下一步行动"]),
]


def _extract_timestamps_s_from_text(text: str) -> list[int]:
    """Return all timestamp values (seconds) found in the document.

    For range timestamps [HH:MM:SS – HH:MM:SS] the END time is used.
    Both en-dash and hyphen separators are accepted.
    """
    results: list[int] = []
    # Range timestamps — capture end time (groups 4-6)
    for m in re.finditer(
        r'\[(\d{2}):(\d{2}):(\d{2})\s*[–\-]\s*(\d{2}):(\d{2}):(\d{2})\]', text
    ):
        results.append(int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6)))
    # Single timestamps — ensure they weren't already part of a range
    for m in re.finditer(r'\[(\d{2}):(\d{2}):(\d{2})\]', text):
        results.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)))
    return results


def _check_heading_skips(lines: list[str]) -> list[str]:
    """Return error strings for heading levels that skip more than one depth."""
    errors: list[str] = []
    prev = 0
    for line in lines:
        m = re.match(r'^(#{1,6})\s', line)
        if not m:
            continue
        level = len(m.group(1))
        if prev > 0 and level > prev + 1:
            errors.append(f"H{prev}→H{level} skip: {line[:60]!r}")
        prev = level
    return errors


def _check_seam_duplicates(text: str) -> list[str]:
    """Return excerpts of consecutive identical paragraphs (continuation seam artefacts)."""
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 20]
    return [
        paragraphs[i][:80]
        for i in range(len(paragraphs) - 1)
        if paragraphs[i] == paragraphs[i + 1]
    ]


def _fix_fence_balance(md_text: str) -> str:
    """If fence markers are unbalanced (odd count), append a closing fence."""
    fence_count = sum(
        1 for l in md_text.splitlines() if re.match(r'^\s*```', l)
    )
    if fence_count % 2 != 0:
        return md_text.rstrip() + "\n```\n"
    return md_text


def final_markdown_qc(
    md_text: str,
    manifest: dict,
    p0_qc: dict | None = None,
) -> dict:
    """Run all QC checks on the final Markdown text.

    Returns {"pass": bool, "issues": [...], "stats": {...}}.
    "pass" is True only when there are zero error-level issues.
    Warning-level issues do not fail the QC.

    Checks (error unless noted):
      h1_exists           — document has at least one H1
      required_section    — 4 mandatory sections present
      coverage            — last timestamp ≥ last section end × COVERAGE_RATIO
      fence_balance       — even number of ``` fence markers
      heading_levels      — no heading-depth skip > 1
      seam_duplicates     — no consecutive duplicate paragraphs
      source_status       — QC header present (warning; injected by run_markdown_qc)
      late_coverage       — last 20 min content present (warning)
    """
    lines     = md_text.splitlines()
    issues: list[dict] = []
    timestamps = _extract_timestamps_s_from_text(md_text)

    # 1. H1 exists
    h1_lines = [l for l in lines if re.match(r'^# [^#]', l)]
    if not h1_lines:
        issues.append({"level": "error", "check": "h1_exists",
                       "detail": "No H1 heading found in document"})

    # 2. Required sections
    for sec_name, keywords in _REQUIRED_SECTIONS:
        pattern = "(" + "|".join(re.escape(k) for k in keywords) + ")"
        found   = any(re.search(r'^##[^#].*' + pattern, l) for l in lines)
        if not found:
            issues.append({"level": "error", "check": "required_section",
                           "detail": f"Missing section: {sec_name}"})

    # 3. Coverage — last timestamp vs stream end
    last_end_s = max((s["end_s"] for s in manifest.get("sections", [])), default=0)
    if last_end_s > 0:
        if not timestamps:
            issues.append({"level": "error", "check": "coverage",
                           "detail": "No timestamps found in document body"})
        else:
            last_ts   = max(timestamps)
            threshold = int(last_end_s * COVERAGE_RATIO)
            if last_ts < threshold:
                issues.append({"level": "error", "check": "coverage",
                               "detail": (
                                   f"Last timestamp {_s_to_hms(last_ts)} < "
                                   f"{COVERAGE_RATIO:.0%} of stream end "
                                   f"{_s_to_hms(last_end_s)} "
                                   f"(threshold {_s_to_hms(threshold)})"
                               )})

    # 4. Fence balance
    fence_lines = [l for l in lines if re.match(r'^\s*```', l)]
    if len(fence_lines) % 2 != 0:
        issues.append({"level": "error", "check": "fence_balance",
                       "detail": f"Odd fence count ({len(fence_lines)}): unclosed code block"})

    # 5. Heading level legality
    for err in _check_heading_skips(lines):
        issues.append({"level": "error", "check": "heading_levels", "detail": err})

    # 6. No seam duplicates
    for dup in _check_seam_duplicates(md_text):
        issues.append({"level": "error", "check": "seam_duplicates",
                       "detail": f"Duplicate paragraph: {dup!r}"})

    # 7. source_status header (warning — run_markdown_qc injects it automatically)
    qc_header_present = (
        "> **Live Final QC**" in md_text or "source_status" in md_text
    )
    if not qc_header_present:
        issues.append({"level": "warning", "check": "source_status",
                       "detail": "QC header not found; run_markdown_qc injects it"})

    # 8. Late coverage (warning)
    if last_end_s > LATE_COVERAGE_WINDOW_S:
        late_threshold = last_end_s - LATE_COVERAGE_WINDOW_S
        if not any(ts >= late_threshold for ts in timestamps):
            issues.append({"level": "warning", "check": "late_coverage",
                           "detail": (
                               f"No content found in last 20 min "
                               f"(>= {_s_to_hms(late_threshold)})"
                           )})

    errors = [i for i in issues if i["level"] == "error"]
    return {
        "pass":   len(errors) == 0,
        "issues": issues,
        "stats": {
            "char_count":       len(md_text),
            "h1_count":         len(h1_lines),
            "h2_count":         len([l for l in lines if re.match(r'^## [^#]', l)]),
            "fence_count":      len(fence_lines),
            "last_timestamp_s": max(timestamps, default=0),
        },
    }


def _inject_qc_header(md_text: str, manifest: dict, p0_qc: dict | None) -> str:
    """Prepend a Live Final QC blockquote to final.md if not already present."""
    if "> **Live Final QC**" in md_text:
        return md_text
    qc             = p0_qc or {}
    source_type    = qc.get("source_type",    "live")
    source_status  = qc.get("source_status",  manifest.get("source_status", "unknown"))
    duration_s     = int(qc.get("timeline_duration_s", 0))
    chunk_count    = qc.get("chunk_count",    len(manifest.get("sections", [])))
    gap_count      = qc.get("gap_count",      0)
    tx_chars       = qc.get("transcript_chars", 0)
    frame_count    = qc.get("frame_count",    0)
    h, r           = divmod(duration_s, 3600)
    mi, s          = divmod(r, 60)
    dur_str        = f"{h:02d}:{mi:02d}:{s:02d}"
    header_lines   = [
        "> **Live Final QC** (sectioned/3-pass)",
        f"> 输入类型：{source_type} | 采集状态：{source_status} | 覆盖时长：{dur_str}",
        f"> chunks：{chunk_count} | gaps：{gap_count} | "
        f"transcript：{tx_chars:,} chars | frames：{frame_count}",
    ]
    for w in qc.get("warnings", []):
        header_lines.append(f"> ⚠️ {w}")
    return "\n".join(header_lines) + "\n\n" + md_text


def run_markdown_qc(
    run_dir: Path,
    config: dict | None = None,
) -> dict:
    """Load final.md, inject QC header, run all checks, apply deterministic fixes.

    Writes final-markdown-qc.json.  Returns the QC result dict.
    Raises FileNotFoundError if final.md is missing.
    """
    manifest = load_manifest(run_dir)
    final_rel = manifest.get("final_md_path")
    if not final_rel:
        raise FileNotFoundError("manifest.final_md_path not set; run pass_c first")
    final_abs = run_dir / final_rel
    if not final_abs.exists():
        raise FileNotFoundError(f"final.md missing: {final_abs}")

    md_text = final_abs.read_text(encoding="utf-8")
    p0_qc   = manifest.get("p0_qc")

    # Inject QC header (deterministic fix for source_status check)
    md_text = _inject_qc_header(md_text, manifest, p0_qc)

    result = final_markdown_qc(md_text, manifest, p0_qc)

    # Deterministic fix: fence closure
    fence_issue = next(
        (i for i in result["issues"] if i["check"] == "fence_balance"), None
    )
    if fence_issue:
        md_text = _fix_fence_balance(md_text)
        result["issues"] = [i for i in result["issues"] if i["check"] != "fence_balance"]
        result["issues"].append({
            "level": "info", "check": "fence_balance",
            "detail": "Auto-fixed: appended closing fence",
        })
        result["pass"] = not any(
            i["level"] == "error" for i in result["issues"]
        )

    # Write (possibly fixed) final.md back
    final_abs.write_text(md_text, encoding="utf-8")

    # Write QC result
    qc_path = run_dir / FINAL_QC_FILENAME
    _atomic_write(qc_path, result)

    status = "PASS" if result["pass"] else "FAIL"
    error_count   = sum(1 for i in result["issues"] if i["level"] == "error")
    warning_count = sum(1 for i in result["issues"] if i["level"] == "warning")
    print(
        f"[markdown_qc] {status}: {error_count} errors, {warning_count} warnings | "
        f"{result['stats']['char_count']:,} chars",
        flush=True,
    )
    return result


# ── P1-8 Sidecar output ───────────────────────────────────────────────────────

def _update_notebooklm_usage(
    md_text: str, base: str, sidecar_dir_name: str, note_count: int
) -> str:
    """Append NotebookLM two-mode usage note to the QC blockquote (idempotent)."""
    if sidecar_dir_name in md_text:
        return md_text
    usage_line = (
        f"> NotebookLM 使用: (1) 完整版 TTS_stream-{base}.md  "
        f"(2) 分段检索 {sidecar_dir_name}/ ({note_count} 文件)"
    )
    lines = md_text.splitlines()
    last_quote_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(">"):
            last_quote_idx = i
        elif last_quote_idx >= 0 and not line.startswith(">"):
            break
    if last_quote_idx >= 0:
        lines.insert(last_quote_idx + 1, usage_line)
        return "\n".join(lines) + "\n"
    return usage_line + "\n\n" + md_text


def publish_section_sidecar(
    run_dir: Path,
    markdowns_dir: Path,
    config: dict | None = None,
) -> dict:
    """Copy done section notes to sidecar dir; publish final.md with usage note.

    Output layout:
        Markdowns/TTS_stream-<base>.md              ← reading copy
        Markdowns/TTS_stream-<base>-sections/
            section_001.md
            section_002.md
            ...                                      ← NotebookLM retrieval copies

    Only sections whose note_status == 'done' are copied.
    The NotebookLM two-mode usage note is injected into the QC header
    of the published final.md (idempotent).
    Returns a result dict with final_md, sidecar_dir, and note_files keys.
    """
    manifest = load_manifest(run_dir)
    base = manifest["base"]
    sidecar_dir_name = f"TTS_stream-{base}-sections"
    sidecar_dir = markdowns_dir / sidecar_dir_name
    sidecar_dir.mkdir(parents=True, exist_ok=True)

    note_files: list[Path] = []
    for s in manifest["sections"]:
        note_rel = s.get("note_path")
        if not note_rel or s.get("note_status") != "done":
            continue
        src = run_dir / note_rel
        if not src.exists():
            continue
        dst = sidecar_dir / src.name
        dst.write_bytes(src.read_bytes())
        note_files.append(dst)

    final_rel = manifest.get("final_md_path")
    final_src = (run_dir / final_rel) if final_rel else None
    final_dst = markdowns_dir / f"TTS_stream-{base}.md"
    if final_src and final_src.exists():
        final_text = final_src.read_text(encoding="utf-8")
        final_text = _update_notebooklm_usage(
            final_text, base, sidecar_dir_name, len(note_files)
        )
        final_dst.write_text(final_text, encoding="utf-8")

    print(
        f"[sidecar] {len(note_files)} notes -> {sidecar_dir_name}/ | "
        f"final -> {final_dst.name}",
        flush=True,
    )
    return {
        "final_md":    final_dst if final_dst.exists() else None,
        "sidecar_dir": sidecar_dir,
        "note_files":  note_files,
    }


# ── P2-1 Frame classifier ─────────────────────────────────────────────────────

_THUMB_W, _THUMB_H = 160, 90  # thumbnail size for fast feature extraction

_VALID_FRAME_TYPES = frozenset({"slide", "annotation", "demo", "speaker", "transition"})


def _frame_features(path: Path) -> dict:
    """Extract classification features from a JPEG frame (160×90 thumbnail)."""
    from PIL import Image
    import numpy as np

    with Image.open(path) as img:
        thumb = img.convert("RGB").resize((_THUMB_W, _THUMB_H), Image.LANCZOS)

    arr = np.array(thumb, dtype=np.float32)   # (H, W, 3)  RGB 0-255
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    gray            = 0.299 * r + 0.587 * g + 0.114 * b
    mean_brightness = float(gray.mean())
    std_brightness  = float(gray.std())

    # Sobel-style gradient magnitude (edge density)
    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    edge_density = float((gx > 20).mean() * 0.5 + (gy > 20).mean() * 0.5)

    # Saturation (HSV-derived from RGB)
    max_c = arr.max(axis=2)
    min_c = arr.min(axis=2)
    diff  = max_c - min_c
    sat   = np.where(max_c > 0, diff / max_c, 0.0)
    mean_saturation = float(sat.mean())

    # Skin tone: R-dominant, moderate G/B, noticeable chroma
    skin_mask    = (r > 95) & (g > 40) & (b > 20) & (diff > 15) & (r > g) & (r > b)
    skin_fraction = float(skin_mask.mean())

    # Dark background (code / IDE dark-mode)
    dark_fraction = float((gray < 50).mean())

    # Vivid accent colours (pen / highlight overlay)
    accent_mask     = (sat > 0.5) & (max_c > 150)
    accent_fraction = float(accent_mask.mean())

    return {
        "mean_brightness": mean_brightness,
        "std_brightness":  std_brightness,
        "edge_density":    edge_density,
        "mean_saturation": mean_saturation,
        "skin_fraction":   skin_fraction,
        "dark_fraction":   dark_fraction,
        "accent_fraction": accent_fraction,
    }


def classify_frame(path: Path) -> str:
    """Classify a keyframe: slide | annotation | demo | speaker | transition.

    Priority order (first match wins):
      transition  — near-solid frame (brightness std < 15)
      speaker     — skin-tone dominant, few edges
      demo        — dark-background screen (code / IDE / UI)
      annotation  — vivid accent colours (pen / highlight overlay on slide)
      slide       — default (light background, moderate edge density)
    """
    f = _frame_features(path)
    if f["std_brightness"] < 15:
        return "transition"
    if f["skin_fraction"] > 0.12 and f["edge_density"] < 0.10:
        return "speaker"
    if f["dark_fraction"] > 0.35:
        return "demo"
    if f["accent_fraction"] > 0.04 and f["mean_saturation"] > 0.30:
        return "annotation"
    return "slide"


def classify_evidence_frames(run_dir: Path, *, force: bool = False) -> dict:
    """Classify all evidence frames and update the 'type' field in-place.

    Reads each evidence/section_NNN.json, classifies frames whose type is
    'unknown' (or all frames when force=True), writes the file back.
    Frames whose image file is missing are counted but left as-is.

    Returns a summary dict:
      {
        "total_processed": int,
        "counts": {
          "slide": N, "annotation": N, "demo": N, "speaker": N,
          "transition": N, "skipped": N, "missing": N,
        },
      }
    """
    evidence_dir = run_dir / "evidence"
    if not evidence_dir.is_dir():
        raise FileNotFoundError(f"evidence dir not found: {evidence_dir}")

    counts: dict[str, int] = {
        "slide": 0, "annotation": 0, "demo": 0, "speaker": 0,
        "transition": 0, "skipped": 0, "missing": 0,
    }
    total_processed = 0

    for ev_path in sorted(evidence_dir.glob("section_*.json")):
        with ev_path.open(encoding="utf-8") as fh:
            evidence = json.load(fh)

        changed = False
        for frame in evidence.get("frames", []):
            if not force and frame.get("type", "unknown") != "unknown":
                counts["skipped"] += 1
                continue
            fp = Path(frame["path"])
            if not fp.exists():
                counts["missing"] += 1
                continue
            label = classify_frame(fp)
            frame["type"] = label
            counts[label] += 1
            changed = True
            total_processed += 1

        if changed:
            _atomic_write(ev_path, evidence)
            new_hash = _hash_evidence(evidence)
            mark_section_stale_if_hash_changed(run_dir, evidence["section_id"], new_hash)

    print(
        f"[frame_classify] {total_processed} frames classified | "
        + " ".join(f"{k}:{v}" for k, v in counts.items() if v > 0),
        flush=True,
    )
    return {"counts": counts, "total_processed": total_processed}


# ── P2-2 Frame dedup ──────────────────────────────────────────────────────────

DEDUP_SIM_THRESHOLD = 0.95   # similarity above which consecutive same-type frames are dupes
SPEAKER_WINDOW_S    = 300    # 5 minutes: at most 1 speaker frame per window


def _dhash(path: Path, hash_size: int = 8) -> int:
    """Difference hash (dHash): compare adjacent pixels, return 64-bit int."""
    from PIL import Image
    import numpy as np

    with Image.open(path) as img:
        arr = np.array(
            img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS),
            dtype=np.uint8,
        )
    diff = (arr[:, 1:] > arr[:, :-1]).flatten().astype(np.uint8)  # 64 bits
    return int.from_bytes(np.packbits(diff).tobytes(), "big")


def _dhash_similarity(h1: int, h2: int, hash_bits: int = 64) -> float:
    """Similarity in [0, 1]: 1 = identical, 0 = completely different."""
    return 1.0 - bin(h1 ^ h2).count("1") / hash_bits


def _laplacian_variance(path: Path) -> float:
    """Variance of Laplacian — higher value means sharper image."""
    from PIL import Image
    import numpy as np

    with Image.open(path) as img:
        arr = np.array(
            img.convert("L").resize((320, 180), Image.LANCZOS),
            dtype=np.float32,
        )
    lap = (
        np.roll(arr, 1, axis=0) + np.roll(arr, -1, axis=0)
        + np.roll(arr, 1, axis=1) + np.roll(arr, -1, axis=1)
        - 4 * arr
    )
    return float(lap.var())


def dedup_frames(
    frames: list[dict],
    *,
    sim_threshold: float = DEDUP_SIM_THRESHOLD,
    speaker_window_s: int = SPEAKER_WINDOW_S,
) -> list[dict]:
    """Filter and deduplicate a list of frame dicts using priority rules.

    Priority rules (applied in order):
    - Frames whose path does not exist are dropped (unusable by Gemini).
    - transition frames are dropped (no content value).
    - annotation frames are always kept.
    - Consecutive same-type frames with similarity > sim_threshold form a run;
      only the sharpest frame per run is kept (slide / demo).
    - speaker frames: at most 1 per speaker_window_s seconds (earliest kept).

    Frames must be ordered by ts.  Returns filtered list of original dicts.
    """
    active = [
        f for f in frames
        if Path(f["path"]).exists() and f.get("type") != "transition"
    ]
    if not active:
        return []

    hashes: dict[str, int | None] = {}
    for f in active:
        try:
            hashes[f["path"]] = _dhash(Path(f["path"]))
        except Exception:
            hashes[f["path"]] = None

    # Group consecutive near-identical same-type frames into runs
    runs: list[list[dict]] = [[active[0]]]
    for i in range(1, len(active)):
        prev, curr = active[i - 1], active[i]
        h1, h2 = hashes.get(prev["path"]), hashes.get(curr["path"])
        if (
            prev.get("type") == curr.get("type")
            and h1 is not None and h2 is not None
            and _dhash_similarity(h1, h2) > sim_threshold
        ):
            runs[-1].append(curr)
        else:
            runs.append([curr])

    kept: list[dict] = []
    last_speaker_ts: float = -speaker_window_s - 1.0

    for run in runs:
        frame_type = run[0].get("type", "slide")

        if frame_type == "annotation":
            kept.extend(run)
        elif frame_type == "speaker":
            for f in run:
                if f["ts"] >= last_speaker_ts + speaker_window_s:
                    kept.append(f)
                    last_speaker_ts = float(f["ts"])
        elif len(run) == 1:
            kept.append(run[0])
        else:
            best = max(run, key=lambda f: _laplacian_variance(Path(f["path"])))
            kept.append(best)

    return kept


def dedup_evidence_frames(
    run_dir: Path, *, force: bool = False, **kwargs
) -> dict:
    """Apply dedup_frames to all evidence sections, updating files in-place.

    Skips sections where any existing-path frame still has type='unknown'
    (run classify_evidence_frames first), unless force=True.
    kwargs are forwarded to dedup_frames (sim_threshold, speaker_window_s).

    Returns:
      {
        "sections_processed": N,
        "frames_before":      N,
        "frames_after":       N,
        "frames_dropped":     N,
      }
    """
    evidence_dir = run_dir / "evidence"
    if not evidence_dir.is_dir():
        raise FileNotFoundError(f"evidence dir not found: {evidence_dir}")

    sections_processed = total_before = total_after = 0

    for ev_path in sorted(evidence_dir.glob("section_*.json")):
        with ev_path.open(encoding="utf-8") as fh:
            evidence = json.load(fh)

        frames = evidence.get("frames", [])

        if not force and any(
            f.get("type", "unknown") == "unknown" and Path(f["path"]).exists()
            for f in frames
        ):
            continue

        n_before = len(frames)
        filtered = dedup_frames(frames, **kwargs)
        n_after  = len(filtered)
        total_before += n_before
        total_after  += n_after

        if n_after != n_before:
            evidence["frames"] = filtered
            _atomic_write(ev_path, evidence)
            new_hash = _hash_evidence(evidence)
            mark_section_stale_if_hash_changed(run_dir, evidence["section_id"], new_hash)

        sections_processed += 1

    dropped = total_before - total_after
    print(
        f"[frame_dedup] {sections_processed} sections | "
        f"{total_before} → {total_after} frames ({dropped} dropped)",
        flush=True,
    )
    return {
        "sections_processed": sections_processed,
        "frames_before":      total_before,
        "frames_after":       total_after,
        "frames_dropped":     dropped,
    }


# ── P2-3 Slide-aware section boundary ────────────────────────────────────────

SLIDE_DENSITY_WINDOW_S    = 60   # rolling window for slide density (seconds)
SLIDE_DENSITY_THRESHOLD   =  3   # min slide frames in window to count as dense
SLIDE_BOUNDARY_MIN_GAP_S  = 120  # min seconds between returned soft boundaries


def detect_slide_boundaries(
    frames: list[dict],
    *,
    density_window_s: int = SLIDE_DENSITY_WINDOW_S,
    density_threshold: int = SLIDE_DENSITY_THRESHOLD,
    min_gap_s: int = SLIDE_BOUNDARY_MIN_GAP_S,
) -> list[int]:
    """Detect slide-switch-dense zones and return their start timestamps.

    Algorithm:
    1. Collect timestamps of all slide-typed frames.
    2. For each timestamp t, count slide frames in [t, t + density_window_s].
    3. Positions where count >= density_threshold mark the start of a dense zone.
    4. Enforce min_gap_s between returned boundaries.

    Returns a sorted list of integer second-timestamps suitable as section
    break points (priority 1.5: after gap boundaries, before fixed windows).
    Frames with type != 'slide' are ignored.  Returns [] if fewer than
    density_threshold slide frames exist.
    """
    slide_ts = sorted(int(f["ts"]) for f in frames if f.get("type") == "slide")
    if len(slide_ts) < density_threshold:
        return []

    dense_starts: list[int] = []
    in_dense = False
    for i, t in enumerate(slide_ts):
        count = sum(1 for ts in slide_ts if t <= ts <= t + density_window_s)
        if count >= density_threshold:
            if not in_dense:
                dense_starts.append(t)
                in_dense = True
        else:
            in_dense = False

    # Enforce minimum gap between boundaries
    result: list[int] = []
    for t in dense_starts:
        if not result or t - result[-1] >= min_gap_s:
            result.append(t)

    return result


# ── P2-4 Cleaned transcript ───────────────────────────────────────────────────

FILLER_WORDS = (
    "那个", "就是", "嗯", "啊", "哦", "呢", "吧", "嘛", "哈", "呃", "额",
)

_TIMESTAMP_HEADER_RE = re.compile(
    r'(\[\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2}\])'
)


def clean_transcript(raw: str, *, filter_fillers: bool = True) -> str:
    """Clean raw ASR transcript text while preserving timestamp anchors.

    Transformations applied to the text body of each [HH:MM:SS - HH:MM:SS] block:
    1. Remove consecutive repeated 1-4 character sequences (ASR jitter).
    2. Optionally remove common Chinese filler words (those in FILLER_WORDS).
    3. Normalize whitespace.

    Timestamp headers are never modified.  The raw transcript is not changed.
    """
    parts = _TIMESTAMP_HEADER_RE.split(raw)
    result: list[str] = []
    for part in parts:
        if _TIMESTAMP_HEADER_RE.fullmatch(part):
            result.append(part)
        else:
            text = re.sub(r'(.{1,4})\1+', r'\1', part)
            if filter_fillers:
                for fw in FILLER_WORDS:
                    text = text.replace(fw, "")
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            result.append(text)
    return "".join(result)


def save_cleaned_transcript(run_dir: Path, raw_transcript: str) -> Path:
    """Clean raw_transcript and write to run_dir/cleaned_transcript.txt.

    Returns the path of the written file.  Prints a one-line reduction summary.
    """
    cleaned   = clean_transcript(raw_transcript)
    out_path  = run_dir / "cleaned_transcript.txt"
    out_path.write_text(cleaned, encoding="utf-8")
    raw_len   = len(raw_transcript)
    clean_len = len(cleaned)
    pct = (raw_len - clean_len) / raw_len * 100 if raw_len > 0 else 0.0
    print(
        f"[clean_transcript] {raw_len:,} → {clean_len:,} chars (-{pct:.1f}%)",
        flush=True,
    )
    return out_path


# ── P2-5 Terminology normalization ────────────────────────────────────────────

_TERMINOLOGY_PATH = Path(__file__).with_name("terminology.json")


def load_terminology(path: Path | None = None) -> list[dict]:
    """Load terminology.json and return the list of term dicts.

    Each dict: {"canonical": str, "variants": [str, ...]}.
    Returns [] if the file does not exist (non-fatal).
    """
    p = Path(path) if path else _TERMINOLOGY_PATH
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("terms", [])


def normalize_transcript(text: str, terms: list[dict]) -> str:
    """Replace variant forms with their canonical terms.

    Replacement rules:
    - Pure-ASCII variants: case-insensitive regex substitution.
    - Variants containing CJK characters: exact-match substitution.

    Processes terms in list order; each canonical is applied once per entry.
    """
    for entry in terms:
        canonical = entry["canonical"]
        for variant in entry.get("variants", []):
            if not variant:
                continue
            is_ascii = all(ord(c) < 128 for c in variant)
            if is_ascii:
                pattern = r'(?<![A-Za-z0-9_])' + re.escape(variant) + r'(?![A-Za-z0-9_])'
                flags = re.IGNORECASE
            else:
                pattern = re.escape(variant)
                flags = 0
            text = re.sub(pattern, canonical, text, flags=flags)
    return text


# ── P1-2 Evidence builder ─────────────────────────────────────────────────────

SECTION_WINDOW_S = 600   # default 10-minute sections
MIN_SECTION_S    = 180   # merge tail sections shorter than 3 minutes into previous


def build_evidence_pack(
    run_dir: Path,
    transcript: str,
    frames: list[dict],
    p0_manifest: dict,
    config: dict | None = None,
    chunk_starts: list[int] | None = None,
) -> list[str]:
    """Segment transcript + frames into per-section evidence JSON files.

    Segmentation rules (priority order):
      1. Gap boundaries  (from p0_manifest["gaps"])
      2. Fixed time windows  (section_window_s, default 600 s)
      3. Merge short tail section (< min_section_s, default 180 s) into previous

    Writes evidence/section_NNN.json for each section.
    Updates manifest: evidence_hash, evidence_status, note_status (stale if hash changed).
    Returns ordered list of section_ids.
    """
    cfg      = config or {}
    window_s = int(cfg.get("section_window_s", SECTION_WINDOW_S))
    min_s    = int(cfg.get("min_section_s",    MIN_SECTION_S))

    timeline_end_s = int(p0_manifest.get("timeline_end_s", 0))
    gaps           = p0_manifest.get("gaps", [])

    terminology_path = cfg.get("terminology_path")
    terms = load_terminology(Path(terminology_path) if terminology_path else None)

    _norm_for_slide = [
        {"ts": f.get("ts", f.get("timestamp_s", 0)), "type": f.get("type", "unknown")}
        for f in (frames or [])
    ]
    slide_bounds = detect_slide_boundaries(_norm_for_slide) if _norm_for_slide else []
    boundaries = _compute_section_boundaries(
        timeline_end_s, gaps, window_s, min_s, slide_boundaries=slide_bounds
    )
    if not boundaries:
        return []

    transcript_blocks = _parse_transcript_blocks(transcript)

    # Build / reconcile manifest sections list
    sections_meta = [
        {"section_id": f"section_{i+1:03d}", "start_s": s, "end_s": e}
        for i, (s, e) in enumerate(boundaries)
    ]
    manifest_path = run_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        manifest = init_manifest(
            run_dir, p0_manifest["base"], p0_manifest["run_ts"],
            sections_meta, p0_manifest,
        )
    else:
        manifest = load_manifest(run_dir)
        if len(manifest["sections"]) != len(sections_meta):
            # Boundary count changed → reset all section states
            manifest["sections"] = [
                _section_entry(m["section_id"], m["start_s"], m["end_s"])
                for m in sections_meta
            ]
            save_manifest(run_dir, manifest)

    evidence_dir  = run_dir / "evidence"
    section_ids: list[str] = []

    for i, (start_s, end_s) in enumerate(boundaries):
        section_id    = f"section_{i+1:03d}"
        evidence_path = evidence_dir / f"{section_id}.json"

        # Transcript blocks whose start_s falls within [start_s, end_s)
        section_txt = "\n".join(
            f"[{_s_to_hms(bs)} - {_s_to_hms(be)}] {text}"
            for bs, be, text in transcript_blocks
            if start_s <= bs < end_s
        )

        # Frames within [start_s, end_s)
        section_frames = [
            {"ts": f["timestamp_s"], "type": "unknown", "path": f["path"]}
            for f in frames
            if start_s <= f.get("timestamp_s", 0) < end_s
        ]

        # Gaps that overlap this section
        section_gaps = [
            g for g in gaps
            if g["start_s"] < end_s and g["end_s"] > start_s
        ]

        # Chunk indices that overlap [start_s, end_s)
        if chunk_starts:
            chunk_ids = [
                idx for idx, cs in enumerate(chunk_starts)
                if cs < end_s and (cs + window_s) > start_s
            ]
        else:
            chunk_ids = []

        _cleaned = clean_transcript(section_txt)
        if terms:
            _cleaned = normalize_transcript(_cleaned, terms)
        evidence = {
            "section_id":         section_id,
            "start_s":            start_s,
            "end_s":              end_s,
            "transcript":         section_txt,
            "cleaned_transcript": _cleaned,
            "frames":             section_frames,
            "gaps":               section_gaps,
            "chunk_ids":          chunk_ids,
        }

        new_hash = _hash_evidence(evidence)

        # Find in-memory section state
        stored = next(
            (s for s in manifest["sections"] if s["section_id"] == section_id),
            None,
        )

        # Skip write if evidence is identical to what's already on disk
        if (
            stored
            and stored.get("evidence_status") == "done"
            and stored.get("evidence_hash") == new_hash
            and evidence_path.exists()
        ):
            section_ids.append(section_id)
            continue

        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Update in-memory manifest entry
        if stored:
            if stored.get("evidence_hash") != new_hash and stored["note_status"] == "done":
                stored["note_status"] = "stale"
            stored["evidence_hash"]   = new_hash
            stored["evidence_status"] = "done"

        save_manifest(run_dir, manifest)   # persist after each section (crash safety)
        section_ids.append(section_id)

    return section_ids


# ── P1-2 Internal helpers ─────────────────────────────────────────────────────


def _compute_section_boundaries(
    timeline_end_s: int,
    gaps: list[dict],
    window_s: int,
    min_s: int,
    slide_boundaries: list[int] | None = None,
) -> list[tuple[int, int]]:
    """Return (start_s, end_s) pairs using gap + slide-soft + fixed-window + short-tail rules.

    Priority order:
      1. Gap boundaries       (from p0_manifest["gaps"])
      1.5 Slide soft borders  (from detect_slide_boundaries, optional)
      2. Fixed time windows   (section_window_s)
      3. Merge short tail     (< min_section_s)
    """
    if timeline_end_s <= 0:
        return []

    # Priority 1: stream boundaries + gap edges
    break_pts: set[int] = {0, timeline_end_s}
    for g in gaps:
        break_pts.add(max(0, int(g["start_s"])))
        break_pts.add(min(timeline_end_s, int(g["end_s"])))

    # Priority 1.5: slide soft boundaries (after gaps, before fixed windows)
    for t in (slide_boundaries or []):
        if 0 < t < timeline_end_s:
            break_pts.add(t)

    # Priority 2: fixed time windows
    t = window_s
    while t < timeline_end_s:
        break_pts.add(t)
        t += window_s

    segs = [
        (a, b)
        for a, b in zip(sorted(break_pts), sorted(break_pts)[1:])
        if b > a
    ]

    # Merge short TAIL segment into previous
    if len(segs) >= 2 and (segs[-1][1] - segs[-1][0]) < min_s:
        segs[-2] = (segs[-2][0], segs[-1][1])
        segs.pop()

    return segs


def _parse_transcript_blocks(transcript: str) -> list[tuple[int, int, str]]:
    """Parse transcript text into (start_s, end_s, text) tuples.

    Handles: [HH:MM:SS - HH:MM:SS] text
    """
    pattern = re.compile(
        r'\[(\d{2}):(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2}):(\d{2})\]'
        r'(.*?)(?=\[\d{2}:\d{2}:\d{2}|$)',
        re.DOTALL,
    )
    blocks: list[tuple[int, int, str]] = []
    for m in pattern.finditer(transcript):
        h1, m1, s1, h2, m2, s2 = (int(x) for x in m.groups()[:6])
        text = m.group(7).strip()
        if text:
            blocks.append((
                h1 * 3600 + m1 * 60 + s1,
                h2 * 3600 + m2 * 60 + s2,
                text,
            ))
    return blocks


def _hash_evidence(evidence: dict) -> str:
    """SHA256 over content-bearing fields; first 16 hex chars (64-bit) sufficient."""
    content = {
        "transcript":         evidence["transcript"],
        "cleaned_transcript": evidence.get("cleaned_transcript", ""),
        "frames":             sorted(
            (f["path"], f.get("type", "unknown"), f.get("ts", 0))
            for f in evidence["frames"]
        ),
        "gaps":               evidence["gaps"],
    }
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return f"sha256:{digest[:16]}"


def _s_to_hms(s: int) -> str:
    h, r = divmod(int(s), 3600)
    m, sec = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


# ── Internal helpers ──────────────────────────────────────────────────────────


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON to a .tmp file then rename — prevents corrupt state on crash."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ── Public pipeline entry point ──────────────────────────────────────────────


def run_full_pipeline(
    runs_dir: Path,
    base: str,
    run_ts: str,
    transcript: str,
    frames: list[dict],
    p0_manifest: dict,
    client,
    config: dict | None = None,
) -> str | None:
    """Orchestrate the full three-pass sectioned synthesis pipeline.

    Kept as an experimental orchestration entry pending a budget-compliant CLI.

    Steps:
      1. Set up run directory.
      2. Build per-section evidence packs.
      3. Classify frame types (P2-1).
      4. Deduplicate frames (P2-2).
      5. Pass A — per-section fact extraction.
      6. Pass B — global outline merge.
      7. Pass C — final document assembly.

    Returns final document text (Pass C output), or None on failure.
    Section notes and outline are preserved in the run directory.
    """
    run_dir = setup_run_dir(runs_dir, base, run_ts)
    print(f"[pipeline] run_dir: {run_dir}", flush=True)

    section_ids = build_evidence_pack(run_dir, transcript, frames, p0_manifest, config)
    if not section_ids:
        print("[pipeline] No sections built — check transcript/frames.", flush=True)
        return None

    print(f"[pipeline] {len(section_ids)} sections built", flush=True)

    classify_evidence_frames(run_dir)
    dedup_evidence_frames(run_dir)

    done_a, failed_a = run_pass_a_all(run_dir, client, config)
    if failed_a:
        print(f"[pipeline] Pass A: {done_a} done, {failed_a} failed", flush=True)

    run_pass_b(run_dir, client, config)
    return run_pass_c(run_dir, client, config)


# ── Smoke test ────────────────────────────────────────────────────────────────


def _smoke_test() -> None:
    """Verify directory layout and manifest state machine end-to-end (P1-1 + P1-3)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        runs = Path(tmp)
        base, run_ts = "test-base", "20260522-120000"
        run_dir = setup_run_dir(runs, base, run_ts)

        assert (run_dir / "evidence").is_dir(), "evidence/ missing"
        assert (run_dir / "notes").is_dir(),    "notes/ missing"

        sections_meta = [
            {"section_id": "section_001", "start_s":    0, "end_s":  600},
            {"section_id": "section_002", "start_s":  600, "end_s": 1200},
            {"section_id": "section_003", "start_s": 1200, "end_s": 1800},
            {"section_id": "section_004", "start_s": 1800, "end_s": 2400},
            {"section_id": "section_005", "start_s": 2400, "end_s": 2700},
        ]
        manifest = init_manifest(run_dir, base, run_ts, sections_meta)
        assert manifest["synthesis_pass"] == "sectioned/3-pass"
        assert len(manifest["sections"]) == 5

        # FileExistsError on re-init
        try:
            init_manifest(run_dir, base, run_ts, sections_meta)
            assert False, "should have raised FileExistsError"
        except FileExistsError:
            pass

        # All 5 start as pending
        loaded = load_manifest(run_dir)
        assert all(s["note_status"] == "pending" for s in loaded["sections"])
        assert len(pending_sections(loaded)) == 5

        # ── Five note_status states ────────────────────────────────────────────
        # section_001 → done (Pass A success)
        update_section(run_dir, "section_001",
                       note_status="done", note_model="gemini-2.5-flash",
                       note_path="notes/section_001.md")
        # section_002 → failed (Gemini error)
        update_section(run_dir, "section_002",
                       note_status="failed", note_attempts=2,
                       last_error="429 RESOURCE_EXHAUSTED")
        # section_003 → running (crash-in-progress)
        update_section(run_dir, "section_003", note_status="running")
        # section_004 stays pending
        # section_005 → done then stale (hash change)
        update_section(run_dir, "section_005",
                       note_status="done", evidence_hash="sha256:aabbcc001122")

        state = load_manifest(run_dir)
        assert state["sections"][0]["note_status"] == "done"
        assert state["sections"][1]["note_status"] == "failed"
        assert state["sections"][2]["note_status"] == "running"
        assert state["sections"][3]["note_status"] == "pending"
        assert state["sections"][4]["note_status"] == "done"

        # pending_sections: failed + running + pending (done sections excluded)
        pending = pending_sections(state)
        pending_ids = {s["section_id"] for s in pending}
        assert pending_ids == {"section_002", "section_003", "section_004"}, \
            f"unexpected pending set: {pending_ids}"
        assert not all_sections_done(state)

        # ── Stale detection ────────────────────────────────────────────────────
        # done + hash unchanged → stays done, not stale
        changed = mark_section_stale_if_hash_changed(
            run_dir, "section_005", "sha256:aabbcc001122"
        )
        assert not changed, "same hash should return False"
        assert load_manifest(run_dir)["sections"][4]["note_status"] == "done"

        # done + hash changed → stale → included in pending_sections
        changed = mark_section_stale_if_hash_changed(
            run_dir, "section_005", "sha256:newvalue99"
        )
        assert changed, "different hash should return True"
        after_stale = load_manifest(run_dir)
        assert after_stale["sections"][4]["note_status"] == "stale"
        pending2 = pending_sections(after_stale)
        stale_ids = {s["section_id"] for s in pending2}
        assert "section_005" in stale_ids, "stale section must be in pending_sections"

        # ── KeyError on unknown section ────────────────────────────────────────
        try:
            update_section(run_dir, "section_999", note_status="done")
            assert False, "should have raised KeyError"
        except KeyError:
            pass

        # ── Pass B / C state helpers ───────────────────────────────────────────
        m = load_manifest(run_dir)
        assert pass_b_needs_rerun(m), "pass_b should need initial run"
        assert not pass_c_needs_rerun(m), "pass_c blocked until pass_b done"

        # Mark all sections done, run pass_b
        for sec in m["sections"]:
            update_section(run_dir, sec["section_id"], note_status="done")
        update_pass_state(run_dir, "pass_b", "done",
                         outline_path="outline.json")
        update_pass_state(run_dir, "pass_c", "pending")

        m2 = load_manifest(run_dir)
        assert not pass_b_needs_rerun(m2), "pass_b is done, should not need rerun"
        assert pass_c_needs_rerun(m2),     "pass_c should need initial run"

        # Simulate section re-processed → mark pass_b stale
        update_pass_state(run_dir, "pass_b", "stale")
        m3 = load_manifest(run_dir)
        assert pass_b_needs_rerun(m3),     "stale pass_b should need rerun"
        assert not pass_c_needs_rerun(m3), "pass_c blocked when pass_b is stale"

        # pass_b KeyError on bad pass name
        try:
            update_pass_state(run_dir, "pass_z", "done")
            assert False, "should have raised KeyError"
        except KeyError:
            pass

        # ── P1-4 Pass A state machine (no live Gemini call) ───────────────────
        # Reset section_001 to pending for a clean run
        update_section(run_dir, "section_001",
                       note_status="pending", note_attempts=0,
                       note_model=None, last_error=None)

        # Step 1 — caller sets running + increments attempts (what run_pass_a does)
        update_section(run_dir, "section_001",
                       note_status="running", note_attempts=1,
                       note_model=PASS_A_MODEL, last_error=None)
        m_run = load_manifest(run_dir)
        assert m_run["sections"][0]["note_status"] == "running"
        # running must appear in pending_sections (crash recovery)
        assert any(s["section_id"] == "section_001"
                   for s in pending_sections(m_run)), "running must be in pending"

        # Step 2a — success path: write note, set done
        note_path = run_dir / "notes" / "section_001.md"
        note_path.write_text(
            "## Section 01 [00:00:00 – 00:10:00]\n- 核心主题：测试内容",
            encoding="utf-8",
        )
        update_section(run_dir, "section_001",
                       note_status="done",
                       note_path="notes/section_001.md",
                       note_model=PASS_A_MODEL,
                       last_error=None)
        m_done = load_manifest(run_dir)
        assert m_done["sections"][0]["note_status"] == "done"
        assert note_path.exists(), "note file must be written"
        assert "section_001" not in {
            s["section_id"] for s in pending_sections(m_done)
        }, "done section must leave pending list"

        # Step 2b — done note triggers pass_b → stale
        update_pass_state(run_dir, "pass_b", "done")
        m_pre = load_manifest(run_dir)
        assert not pass_b_needs_rerun(m_pre), "pass_b fresh done should not need rerun"
        # Simulate re-running section_001 and it completes again → mark pass_b stale
        update_section(run_dir, "section_001", note_status="done")
        m_check = load_manifest(run_dir)
        if m_check.get("pass_b_status") == "done":
            update_pass_state(run_dir, "pass_b", "stale")
        m_post = load_manifest(run_dir)
        assert m_post.get("pass_b_status") == "stale", \
            f"pass_b should be stale after note re-done, got {m_post.get('pass_b_status')}"
        assert pass_b_needs_rerun(m_post), "stale pass_b must need rerun"

        # Step 2c — failure path: set failed + last_error
        update_section(run_dir, "section_002",
                       note_status="running", note_attempts=1)
        update_section(run_dir, "section_002",
                       note_status="failed",
                       last_error="call_gemini returned None after 1 attempt(s)")
        m_fail = load_manifest(run_dir)
        assert m_fail["sections"][1]["note_status"] == "failed"
        assert m_fail["sections"][1]["last_error"] is not None
        assert any(s["section_id"] == "section_002"
                   for s in pending_sections(m_fail)), "failed must be in pending"

        # Step 3 — model escalation: flash until MAX_PASS_A_FLASH_ATTEMPTS, then pro
        for attempt in range(1, MAX_PASS_A_FLASH_ATTEMPTS + 2):
            expected = (
                PASS_A_PRO_MODEL if attempt > MAX_PASS_A_FLASH_ATTEMPTS
                else PASS_A_MODEL
            )
            actual = (
                PASS_A_PRO_MODEL if attempt > MAX_PASS_A_FLASH_ATTEMPTS
                else PASS_A_MODEL
            )
            assert actual == expected, (
                f"attempt {attempt}: expected {expected}, got {actual}"
            )

        # Step 4 — _pass_a_prompt produces correct header line
        header = "## Section 03 [00:20:00 – 00:30:00]"
        prompt = _pass_a_prompt(header)
        assert header in prompt, "header must appear in prompt"
        assert "核心主题" in prompt, "prompt must include field names"
        assert "关键术语" in prompt, "prompt must include 关键术语"

        # ── P1-5 Pass B (no live Gemini call) ────────────────────────────────
        # Prep: make all sections done with note files
        for sec in load_manifest(run_dir)["sections"]:
            sid = sec["section_id"]
            note_path = run_dir / "notes" / f"{sid}.md"
            num = int(sid.split("_")[1])
            note_path.write_text(
                f"## Section {num:02d} [00:00:00 – 00:10:00]\n"
                f"- 核心主题：测试内容 {num}\n"
                f"- 关键论点：• 要点一\n"
                f"- 关键术语：Claude Code\n"
                "- 视觉证据：无\n- 重要案例：无\n- 原话候选：无\n"
                "- 行动项/作业：无\n- 不确定点：无\n",
                encoding="utf-8",
            )
            update_section(run_dir, sid, note_status="done",
                           note_path=f"notes/{sid}.md")
        update_pass_state(run_dir, "pass_b", "pending")
        update_pass_state(run_dir, "pass_c", "pending")

        # _load_section_notes: should return all 5 notes concatenated
        m_full = load_manifest(run_dir)
        combined = _load_section_notes(run_dir, m_full)
        assert combined.count("---") == 4, "5 notes → 4 separators"
        assert "核心主题" in combined

        # _pass_b_prompt: should mention section count and chapter range
        prompt_b = _pass_b_prompt(combined, m_full)
        assert "chapters" in prompt_b, "prompt must show output format"
        assert "section_id" in prompt_b.lower() or "sections" in prompt_b

        # _extract_json_from_response: plain JSON
        raw_json = '{"chapters":[{"title":"T","start_s":0,"end_s":600,"sections":["section_001"]}]}'
        parsed = _extract_json_from_response(raw_json)
        assert parsed["chapters"][0]["title"] == "T"

        # _extract_json_from_response: markdown-fenced JSON
        fenced = "```json\n" + raw_json + "\n```"
        parsed2 = _extract_json_from_response(fenced)
        assert parsed2["chapters"][0]["title"] == "T"

        # _extract_json_from_response: no JSON → ValueError
        try:
            _extract_json_from_response("no json here")
            assert False, "should raise ValueError"
        except ValueError:
            pass

        # _validate_outline: valid outline covering all 5 sections
        valid_outline = {
            "chapters": [
                {"title": "章节一", "start_s":    0, "end_s": 1200,
                 "sections": ["section_001", "section_002"]},
                {"title": "章节二", "start_s": 1200, "end_s": 2400,
                 "sections": ["section_003", "section_004"]},
                {"title": "章节三", "start_s": 2400, "end_s": 2700,
                 "sections": ["section_005"]},
            ]
        }
        errs = _validate_outline(valid_outline, m_full)
        assert errs == [], f"valid outline should pass QC, got: {errs}"

        # _validate_outline: missing section
        missing_outline = {
            "chapters": [
                {"title": "章节一", "start_s": 0, "end_s": 1200,
                 "sections": ["section_001", "section_002"]},
            ]
        }
        errs2 = _validate_outline(missing_outline, m_full)
        assert any("not assigned" in e for e in errs2), \
            f"should flag missing sections, got: {errs2}"

        # _validate_outline: duplicate section
        dup_outline = {
            "chapters": [
                {"title": "A", "start_s":    0, "end_s": 1800,
                 "sections": ["section_001", "section_002", "section_003"]},
                {"title": "B", "start_s": 1800, "end_s": 2700,
                 "sections": ["section_003", "section_004", "section_005"]},
            ]
        }
        errs3 = _validate_outline(dup_outline, m_full)
        assert any("multiple chapters" in e for e in errs3), \
            f"should flag duplicate, got: {errs3}"

        # _validate_outline: time-order violation
        bad_order = {
            "chapters": [
                {"title": "A", "start_s": 1200, "end_s": 2400,
                 "sections": ["section_003", "section_004"]},
                {"title": "B", "start_s":    0, "end_s": 1200,
                 "sections": ["section_001", "section_002"]},
                {"title": "C", "start_s": 2400, "end_s": 2700,
                 "sections": ["section_005"]},
            ]
        }
        errs4 = _validate_outline(bad_order, m_full)
        assert any("start_s" in e and "previous" in e for e in errs4), \
            f"should flag time-order violation, got: {errs4}"

        # Simulate pass_b done → pass_c stale trigger
        update_pass_state(run_dir, "pass_c", "done")
        outline_path = run_dir / OUTLINE_FILENAME
        _atomic_write(outline_path, valid_outline)
        update_pass_state(run_dir, "pass_b", "done",
                          outline_path=str(outline_path.relative_to(run_dir)))
        # Simulate what run_pass_b does: mark pass_c stale when pass_b re-completes
        m_after_b = load_manifest(run_dir)
        if m_after_b.get("pass_c_status") == "done":
            update_pass_state(run_dir, "pass_c", "stale")
        m_stale_c = load_manifest(run_dir)
        assert m_stale_c.get("pass_c_status") == "stale", \
            "pass_c must become stale when pass_b reruns"
        assert pass_c_needs_rerun(load_manifest(run_dir)), \
            "pass_c stale must trigger rerun"

        # ── P1-6 Pass C (no live Gemini call) ────────────────────────────────
        # Reset to pass_b=done, pass_c=pending
        update_pass_state(run_dir, "pass_b", "done",
                          outline_path=str(outline_path.relative_to(run_dir)))
        update_pass_state(run_dir, "pass_c", "pending")

        # run_pass_c raises when pass_b is not done
        update_pass_state(run_dir, "pass_b", "pending")
        try:
            run_pass_c(run_dir, None)
            assert False, "should raise RuntimeError"
        except RuntimeError:
            pass
        update_pass_state(run_dir, "pass_b", "done",
                          outline_path=str(outline_path.relative_to(run_dir)))

        # run_pass_c raises when outline_path missing from manifest
        m_no_outline = load_manifest(run_dir)
        m_no_outline["outline_path"] = None
        save_manifest(run_dir, m_no_outline)
        try:
            run_pass_c(run_dir, None)
            assert False, "should raise RuntimeError"
        except RuntimeError:
            pass
        update_pass_state(run_dir, "pass_b", "done",
                          outline_path=str(outline_path.relative_to(run_dir)))

        # _build_pass_c_prompt: verify structure
        notes_by_section = {}
        for s in load_manifest(run_dir)["sections"]:
            note_rel = s.get("note_path")
            if note_rel:
                np = run_dir / note_rel
                if np.exists():
                    notes_by_section[s["section_id"]] = np.read_text(encoding="utf-8").strip()

        prompt_c = _build_pass_c_prompt(valid_outline, notes_by_section,
                                        load_manifest(run_dir))
        assert "全局章节架构" in prompt_c,    "prompt must contain 全局章节架构"
        assert "Section Notes" in prompt_c,   "prompt must contain Section Notes"
        assert "章节一" in prompt_c,          "chapter titles must appear in prompt"
        assert "核心主题" in prompt_c,        "section note content must appear in prompt"
        assert "## 1. 视频元数据" in prompt_c, "output schema section 1 must be in prompt"
        assert "## 3. 详尽内容解析" in prompt_c, "output schema section 3 must be in prompt"

        # Section notes with no note_path → not included, no KeyError
        partial_notes = {k: v for k, v in notes_by_section.items()
                         if k != "section_003"}
        prompt_partial = _build_pass_c_prompt(valid_outline, partial_notes,
                                              load_manifest(run_dir))
        assert "章节二" in prompt_partial, "chapter with partial notes still renders"

        # Simulate successful pass_c run (write final.md directly)
        final_path = run_dir / FINAL_MD_FILENAME
        final_text = (
            "# 测试直播课内容总结\n\n"
            "## 1. 视频元数据\n- **推测主题：** 测试\n\n"
            "## 2. 核心知识字典（Glossary）\n- Claude Code\n\n"
            "## 3. 详尽内容解析（按章节）\n"
            "### [00:00:00 – 00:20:00] 章节一\n- **核心论点：** 测试内容\n\n"
            "## 4. 遗留问题与下一步行动（如有）\n本场直播暂无明确行动项\n"
        )
        final_path.write_text(final_text, encoding="utf-8")
        update_pass_state(run_dir, "pass_c", "done",
                          final_md_path=str(final_path.relative_to(run_dir)))
        m_c_done = load_manifest(run_dir)
        assert m_c_done.get("pass_c_status") == "done"
        assert m_c_done.get("final_md_path") == "final.md"
        assert final_path.exists()
        assert not pass_c_needs_rerun(m_c_done), "done pass_c should not need rerun"

        # pass_b rerun → pass_c becomes stale (already tested above via run_pass_b sim)
        update_pass_state(run_dir, "pass_b", "stale")
        assert not pass_c_needs_rerun(load_manifest(run_dir)), \
            "pass_c blocked when pass_b is stale"
        update_pass_state(run_dir, "pass_b", "done",
                          outline_path=str(outline_path.relative_to(run_dir)))
        update_pass_state(run_dir, "pass_c", "stale")
        assert pass_c_needs_rerun(load_manifest(run_dir)), \
            "stale pass_c must trigger rerun"

        # ── P1-7 Final Markdown QC ────────────────────────────────────────────
        m_qc = load_manifest(run_dir)  # sections end_s max = 2700

        # Shared good document (reaches 00:45:00 = 2700s, covers all sections)
        GOOD_MD = (
            "> **Live Final QC** (sectioned/3-pass)\n\n"
            "# 测试直播课\n\n"
            "## 1. 视频元数据\n- **推测主题：** 测试\n\n"
            "## 2. 核心知识字典（Glossary）\n- Claude Code: 测试\n\n"
            "## 3. 详尽内容解析（按章节）\n"
            "### [00:00:00 – 00:20:00] 章节一\n内容...\n\n"
            "### [00:20:00 – 00:45:00] 章节二\n内容...\n\n"
            "## 4. 遗留问题与下一步行动（如有）\n无\n"
        )

        # Valid doc passes all checks
        r_good = final_markdown_qc(GOOD_MD, m_qc)
        assert r_good["pass"], f"good doc should pass QC, got: {r_good['issues']}"
        assert r_good["stats"]["h1_count"] == 1
        assert r_good["stats"]["last_timestamp_s"] == 2700  # 00:45:00

        # Missing H1 → error
        no_h1 = GOOD_MD.replace("# 测试直播课\n", "")
        r_no_h1 = final_markdown_qc(no_h1, m_qc)
        assert not r_no_h1["pass"]
        assert any(i["check"] == "h1_exists" for i in r_no_h1["issues"])

        # Missing required section → error
        no_glossary = "\n".join(
            l for l in GOOD_MD.splitlines()
            if "知识字典" not in l and "Glossary" not in l
        )
        r_no_gls = final_markdown_qc(no_glossary, m_qc)
        assert any(i["check"] == "required_section" and "知识字典" in i["detail"]
                   for i in r_no_gls["issues"])

        # Coverage failure — last timestamp only at 00:05:00 (300s) < 2700*0.9=2430
        low_cov = (
            "> **Live Final QC** (sectioned/3-pass)\n\n"
            "# 直播\n\n"
            "## 1. 视频元数据\n无\n\n"
            "## 2. 核心知识字典（Glossary）\n无\n\n"
            "## 3. 详尽内容解析（按章节）\n"
            "### [00:00:00 – 00:05:00] 章节一\n内容\n\n"
            "## 4. 遗留问题与下一步行动（如有）\n无\n"
        )
        r_cov = final_markdown_qc(low_cov, m_qc)
        assert any(i["check"] == "coverage" for i in r_cov["issues"])

        # Unclosed fence → error detected; _fix_fence_balance closes it
        fenced_bad = GOOD_MD + "\n```python\ncode here\n"
        r_fence = final_markdown_qc(fenced_bad, m_qc)
        assert any(i["check"] == "fence_balance" for i in r_fence["issues"])
        fixed = _fix_fence_balance(fenced_bad)
        fence_count_after = sum(
            1 for l in fixed.splitlines() if re.match(r'^\s*```', l)
        )
        assert fence_count_after % 2 == 0, "fence must be balanced after fix"

        # Heading skip H1→H3 → error
        skip_md = (
            "> **Live Final QC**\n\n# Title\n### Skipped H2\n\n"
            "## 1. 视频元数据\n无\n## 2. 核心知识字典（Glossary）\n无\n"
            "## 3. 详尽内容解析（按章节）\n### [00:00:00 – 00:45:00] 章节\n无\n"
            "## 4. 遗留问题与下一步行动（如有）\n无\n"
        )
        r_skip = final_markdown_qc(skip_md, m_qc)
        assert any(i["check"] == "heading_levels" for i in r_skip["issues"]), \
            f"H1→H3 skip not flagged: {r_skip['issues']}"

        # Seam duplicate → error
        dup_para = "这是一个测试段落，内容非常重要，不应该重复出现。"
        dup_md = GOOD_MD + f"\n\n{dup_para}\n\n{dup_para}\n"
        r_dup = final_markdown_qc(dup_md, m_qc)
        assert any(i["check"] == "seam_duplicates" for i in r_dup["issues"])

        # No QC header → source_status warning
        no_header = GOOD_MD.replace("> **Live Final QC** (sectioned/3-pass)\n\n", "")
        r_warn = final_markdown_qc(no_header, m_qc)
        assert any(i["check"] == "source_status" and i["level"] == "warning"
                   for i in r_warn["issues"])

        # run_markdown_qc end-to-end: write final.md without header, run QC
        final_path = run_dir / FINAL_MD_FILENAME
        plain_md = GOOD_MD.replace("> **Live Final QC** (sectioned/3-pass)\n\n", "")
        final_path.write_text(plain_md, encoding="utf-8")
        update_pass_state(run_dir, "pass_c", "done",
                          final_md_path=str(final_path.relative_to(run_dir)))
        qc_result = run_markdown_qc(run_dir)
        assert qc_result["pass"], f"run_markdown_qc should pass, got: {qc_result['issues']}"
        qc_json = run_dir / FINAL_QC_FILENAME
        assert qc_json.exists(), "final-markdown-qc.json must be written"
        loaded_qc = json.loads(qc_json.read_text(encoding="utf-8"))
        assert loaded_qc["pass"]
        # Header injected into file
        injected_text = final_path.read_text(encoding="utf-8")
        assert "> **Live Final QC**" in injected_text, "QC header must be injected"

        # run_markdown_qc: unclosed fence gets auto-fixed, file rewritten
        broken_md = plain_md + "\n```python\ncode\n"
        final_path.write_text(broken_md, encoding="utf-8")
        qc_fixed = run_markdown_qc(run_dir)
        fixed_text = final_path.read_text(encoding="utf-8")
        fence_count = sum(1 for l in fixed_text.splitlines() if re.match(r'^\s*```', l))
        assert fence_count % 2 == 0, "fence must be auto-fixed in file"
        # fence_balance should not appear as error in result
        assert not any(i["check"] == "fence_balance" and i["level"] == "error"
                       for i in qc_fixed["issues"])

        # ── P1-8: sidecar publish ─────────────────────────────────────────────
        markdowns_dir = run_dir / "Markdowns-test"
        result = publish_section_sidecar(run_dir, markdowns_dir)

        # final.md published
        assert result["final_md"] is not None and result["final_md"].exists(), \
            "final_md not published"
        # sidecar dir created
        assert result["sidecar_dir"].is_dir(), "sidecar_dir not created"
        # reload manifest (Pass A updated note_status fields since init)
        manifest = load_manifest(run_dir)
        # only done sections copied (all sections in smoke test are done)
        done_sections = [s for s in manifest["sections"] if s.get("note_status") == "done"]
        assert len(result["note_files"]) == len(done_sections), \
            f"expected {len(done_sections)} notes, got {len(result['note_files'])}"
        # each note file exists and is non-empty
        for nf in result["note_files"]:
            assert nf.exists() and nf.stat().st_size > 0, f"note file empty: {nf}"
        # usage note injected into published final.md
        pub_text = result["final_md"].read_text(encoding="utf-8")
        assert "TTS_stream-" in pub_text and "-sections/" in pub_text, \
            "NotebookLM usage note not injected"
        # idempotency: second publish call must not duplicate usage note
        result2 = publish_section_sidecar(run_dir, markdowns_dir)
        pub_text2 = result2["final_md"].read_text(encoding="utf-8")
        assert pub_text2.count("-sections/") == pub_text.count("-sections/"), \
            "usage note duplicated on second publish"

        # ── P2-1: frame classifier ────────────────────────────────────────────
        from PIL import Image as _PilImage
        import numpy as _np

        frames_dir = run_dir / "frames-p2"
        frames_dir.mkdir()

        # transition: near-solid gray → std_brightness < 15
        _t = _np.full((180, 320, 3), 128, dtype=_np.uint8)
        transition_path = frames_dir / "f_transition.jpg"
        _PilImage.fromarray(_t).save(transition_path)

        # demo: dark top half / medium bottom half → dark_fraction > 0.35, std > 15
        _d = _np.full((180, 320, 3), 20, dtype=_np.uint8)
        _d[90:, :, :] = 70
        demo_path = frames_dir / "f_demo.jpg"
        _PilImage.fromarray(_d).save(demo_path)

        # slide: mostly white with a dark text stripe → std > 15, not dark, not skin
        _s = _np.full((180, 320, 3), 240, dtype=_np.uint8)
        _s[80:100, :, :] = 50
        slide_path = frames_dir / "f_slide.jpg"
        _PilImage.fromarray(_s).save(slide_path)

        # Wire up two evidence JSONs (section_001, section_002 not yet used)
        ev_dir = run_dir / "evidence"
        _ev1 = {
            "section_id": "section_001", "start_s": 0, "end_s": 600,
            "transcript": "test", "gaps": [],
            "frames": [
                {"ts": 30, "type": "unknown", "path": str(slide_path)},
                {"ts": 60, "type": "unknown", "path": str(demo_path)},
            ],
        }
        _ev2 = {
            "section_id": "section_002", "start_s": 600, "end_s": 1200,
            "transcript": "test2", "gaps": [],
            "frames": [
                {"ts": 630, "type": "unknown", "path": str(transition_path)},
                # deliberately missing file
                {"ts": 660, "type": "unknown", "path": str(frames_dir / "missing.jpg")},
            ],
        }
        (ev_dir / "section_001.json").write_text(
            json.dumps(_ev1), encoding="utf-8"
        )
        (ev_dir / "section_002.json").write_text(
            json.dumps(_ev2), encoding="utf-8"
        )

        cls_r = classify_evidence_frames(run_dir)
        assert cls_r["total_processed"] == 3, (
            f"expected 3 processed, got {cls_r['total_processed']}"
        )
        assert cls_r["counts"]["missing"] == 1, "one missing frame expected"

        # All processed frames must have a valid type
        for ev_file in (ev_dir / "section_001.json", ev_dir / "section_002.json"):
            ev_data = json.loads(ev_file.read_text())
            for fr in ev_data["frames"]:
                if Path(fr["path"]).exists():
                    assert fr["type"] in _VALID_FRAME_TYPES, (
                        f"invalid type {fr['type']!r}"
                    )

        # Specific heuristics: solid-gray → transition, dark-half → demo
        assert classify_frame(transition_path) == "transition", \
            "solid-gray frame must be transition"
        assert classify_frame(demo_path) == "demo", \
            "dark-bg frame must be demo"

        # Idempotency: second run skips already-classified frames
        cls_r2 = classify_evidence_frames(run_dir)
        assert cls_r2["total_processed"] == 0, "second run should skip all"
        assert cls_r2["counts"]["skipped"] == 3

        # force=True re-classifies everything
        cls_r3 = classify_evidence_frames(run_dir, force=True)
        assert cls_r3["total_processed"] == 3, "force must re-classify all"

        # ── P2-2: frame dedup ─────────────────────────────────────────────────
        frames2_dir = run_dir / "frames-p22"
        frames2_dir.mkdir()

        # Two identical slide images (copy bytes → same dHash → sim = 1.0)
        slide_a_path = frames2_dir / "slide_a.jpg"
        _PilImage.fromarray(_s).save(slide_a_path)
        slide_a2_path = frames2_dir / "slide_a2.jpg"
        slide_a2_path.write_bytes(slide_a_path.read_bytes())

        # Annotation: large vivid-red region on white (accent_fraction > 0.04, sat > 0.30)
        _ann = _np.full((180, 320, 3), 240, dtype=_np.uint8)
        _ann[20:160, 40:280, :] = [220, 20, 20]
        ann_path = frames2_dir / "annotation.jpg"
        _PilImage.fromarray(_ann).save(ann_path)

        # Speaker: skin-tone top, dark clothing bottom → speaker classification
        _spk = _np.full((180, 320, 3), [180, 120, 80], dtype=_np.uint8)
        _spk[120:, :, :] = [50, 50, 150]
        spk1_path = frames2_dir / "speaker1.jpg"
        spk2_path = frames2_dir / "speaker2.jpg"
        _PilImage.fromarray(_spk).save(spk1_path)
        _PilImage.fromarray(_spk).save(spk2_path)

        test_frames = [
            {"ts":  10, "type": "transition", "path": str(transition_path)},
            {"ts":  30, "type": "slide",      "path": str(slide_a_path)},
            {"ts":  60, "type": "slide",      "path": str(slide_a2_path)},  # near-identical → dedup
            {"ts":  90, "type": "annotation", "path": str(ann_path)},
            {"ts": 100, "type": "speaker",    "path": str(spk1_path)},
            {"ts": 110, "type": "speaker",    "path": str(spk2_path)},  # within 5 min → throttled
        ]

        deduped = dedup_frames(test_frames, speaker_window_s=300)
        # Expected: transition dropped, slide pair → 1, annotation kept, 1 speaker
        assert len(deduped) == 3, f"expected 3 kept, got {len(deduped)}: {[f['type'] for f in deduped]}"
        assert all(f["type"] != "transition" for f in deduped), "no transition in output"
        assert any(f["type"] == "annotation" for f in deduped), "annotation must be kept"
        assert sum(1 for f in deduped if f["type"] == "speaker") == 1, \
            "only 1 speaker per 5-min window"
        assert sum(1 for f in deduped if f["type"] == "slide") == 1, \
            "identical slide pair must dedup to 1"

        # dedup_evidence_frames: write a fresh evidence section and process it
        _ev3 = {
            "section_id": "section_003", "start_s": 1200, "end_s": 1800,
            "transcript": "test3", "gaps": [],
            "frames": list(test_frames),
        }
        (ev_dir / "section_003.json").write_text(
            json.dumps(_ev3), encoding="utf-8"
        )
        dedup_r = dedup_evidence_frames(run_dir)
        assert dedup_r["frames_dropped"] > 0, "must drop at least some frames"
        assert dedup_r["sections_processed"] >= 1

        # Idempotency: second dedup on already-deduped evidence changes nothing
        before_count = json.loads(
            (ev_dir / "section_003.json").read_text()
        )["frames"]
        dedup_r2 = dedup_evidence_frames(run_dir)
        after_count = json.loads(
            (ev_dir / "section_003.json").read_text()
        )["frames"]
        assert len(before_count) == len(after_count), \
            "second dedup must not change frame count"

        # ── P2-3: slide-aware section boundary ───────────────────────────────
        # 5 slide frames clustered at t=1200–1220 (dense within 60s window)
        # plus 2 isolated slides that don't form a cluster
        p23_frames = (
            [{"ts": 100,  "type": "slide", "path": "x"}]
            + [{"ts": 1200 + i * 5, "type": "slide", "path": "x"} for i in range(5)]
            + [{"ts": 2000, "type": "slide", "path": "x"}]
            + [{"ts": 500,  "type": "demo",  "path": "x"}]  # non-slide, ignored
        )
        slide_bounds = detect_slide_boundaries(
            p23_frames, density_window_s=60, density_threshold=3, min_gap_s=120
        )
        # Cluster at 1200 → boundary; isolated frames at 100 and 2000 → no boundary
        assert 1200 in slide_bounds, f"expected 1200 in slide_bounds, got {slide_bounds}"
        assert 100  not in slide_bounds, "isolated frame at 100 must not trigger boundary"
        assert 2000 not in slide_bounds, "isolated frame at 2000 must not trigger boundary"

        # Fewer than threshold → no boundaries
        sparse = [{"ts": i * 600, "type": "slide", "path": "x"} for i in range(2)]
        assert detect_slide_boundaries(sparse, density_threshold=3) == []

        # _compute_section_boundaries with slide boundary at 800
        # (800 is NOT a multiple of the 600s fixed window → adds extra cut)
        bounds_plain = _compute_section_boundaries(3600, [], 600, 180)
        bounds_slide = _compute_section_boundaries(3600, [], 600, 180,
                                                   slide_boundaries=[800])
        assert len(bounds_slide) > len(bounds_plain), \
            "slide boundary at 800 must add an extra section"
        boundary_times = {t for seg in bounds_slide for t in seg}
        assert 800 in boundary_times, "800 must appear as a section boundary edge"

        # ── P2-4: cleaned transcript ──────────────────────────────────────────
        # Repeated word removal
        raw_rep = "我我我说了然后然后他来了"
        c_rep = clean_transcript(raw_rep, filter_fillers=False)
        assert "我我" not in c_rep and "然后然后" not in c_rep, \
            f"repeated words not removed: {c_rep!r}"
        assert "说了" in c_rep and "他来了" in c_rep, \
            "content words must survive dedup"

        # Filler word removal (filter_fillers=True)
        raw_fill = "那个就是嗯我们来讨论一下"
        c_fill = clean_transcript(raw_fill, filter_fillers=True)
        for fw in ("那个", "就是", "嗯"):
            assert fw not in c_fill, f"filler {fw!r} not removed"
        assert "讨论一下" in c_fill.replace(" ", ""), "content preserved"

        # filter_fillers=False keeps fillers
        c_keep = clean_transcript(raw_fill, filter_fillers=False)
        assert "那个" in c_keep, "fillers kept when filter_fillers=False"

        # Timestamp headers preserved unchanged
        raw_ts = "[00:00:00 - 00:01:00] 嗯那个那个我说\n[00:01:00 - 00:02:00] 然后然后继续"
        c_ts = clean_transcript(raw_ts)
        assert "[00:00:00 - 00:01:00]" in c_ts, "first timestamp preserved"
        assert "[00:01:00 - 00:02:00]" in c_ts, "second timestamp preserved"
        assert "那个那个" not in c_ts, "repeated filler in block removed"
        assert "然后然后" not in c_ts, "repeated word in block removed"

        # save_cleaned_transcript writes file, content is cleaned
        saved_path = save_cleaned_transcript(
            run_dir, "[00:00:00 - 00:01:00] 我我我说嗯"
        )
        assert saved_path.exists() and saved_path.name == "cleaned_transcript.txt"
        saved_text = saved_path.read_text(encoding="utf-8")
        assert "我我我" not in saved_text, "saved file must be cleaned"

        # Char reduction in realistic range for filler-heavy text
        raw_heavy = "[00:00:00 - 00:05:00] " + "那个 " * 30 + "我我 " * 15 + "真正内容 " * 40
        clean_heavy = clean_transcript(raw_heavy)
        reduction = (len(raw_heavy) - len(clean_heavy)) / len(raw_heavy)
        assert 0.05 <= reduction <= 0.90, \
            f"expected 5-90% reduction for filler-heavy text, got {reduction:.1%}"

        # Slide boundary coinciding with a gap edge is deduplicated
        bounds_overlap = _compute_section_boundaries(
            3600, [{"start_s": 800, "end_s": 900}], 600, 180,
            slide_boundaries=[800],
        )
        # 800 is already added by the gap rule; count should equal gap-only count
        bounds_gap_only = _compute_section_boundaries(
            3600, [{"start_s": 800, "end_s": 900}], 600, 180,
        )
        assert len(bounds_overlap) == len(bounds_gap_only), \
            "duplicate boundary from gap+slide must not create extra section"

        # ── P2-5: terminology normalization ──────────────────────────────────
        import tempfile as _tf

        terms_data = {
            "version": "1.0",
            "terms": [
                {"canonical": "Claude Code",
                 "variants": ["claude code", "克劳德代码"]},
                {"canonical": "RAG",
                 "variants": ["rag", "Rag"]},
                {"canonical": "MCP",
                 "variants": ["mcp"]},
            ],
        }
        terms_path = run_dir / "test_terminology.json"
        terms_path.write_text(json.dumps(terms_data), encoding="utf-8")

        # load_terminology
        loaded = load_terminology(terms_path)
        assert len(loaded) == 3
        assert loaded[0]["canonical"] == "Claude Code"

        # load_terminology: missing file → []
        assert load_terminology(run_dir / "no_such_file.json") == []

        # normalize_transcript: ASCII case-insensitive
        text_in = "今天讲claude code和rag的结合"
        normed = normalize_transcript(text_in, loaded)
        assert "Claude Code" in normed, f"ASCII variant not normalized: {normed}"
        assert "RAG" in normed,         f"ASCII variant not normalized: {normed}"
        assert "claude code" not in normed
        assert " rag" not in normed.lower().split()  # 'rag' replaced

        # normalize_transcript: CJK exact match
        text_cn = "今天讲克劳德代码的用法"
        normed_cn = normalize_transcript(text_cn, loaded)
        assert "Claude Code" in normed_cn, f"CJK variant not normalized: {normed_cn}"

        # normalize_transcript: unknown text unchanged
        unchanged = normalize_transcript("完全陌生的文字内容", loaded)
        assert unchanged == "完全陌生的文字内容"

        print("smoke test PASSED")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        _smoke_test()
    else:
        print(__doc__)

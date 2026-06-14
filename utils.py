"""Shared utilities for zhihu pipeline scripts.

Extracted from: build_final_markdown.py, build_stream_markdown.py,
                merge_stream_chunks.py, zhihuTTS.py, zhihuTTS_stream.py
"""
from __future__ import annotations

import base64
import re
import sys
import time
from pathlib import Path

__all__ = [
    "fmt_ts", "parse_retry_delay", "extract_run_ts", "call_gemini", "call_qwen",
    # Qwen output QC
    "QWEN_BODY_MIN_TRANSCRIPT_RATIO", "QWEN_FACT_RETENTION_MIN_RATIO",
    "QWEN_NARRATIVE_RETENTION_MIN_RATIO", "QWEN_NARRATIVE_MIN_BLOCKS_PER_WINDOW",
    "QWEN_CRITICAL_FACT_TERMS",
    "extract_qwen_critical_facts", "extract_qwen_narrative_blocks",
    "format_qwen_critical_facts_for_prompt", "format_qwen_narrative_blocks_for_prompt",
    "format_qwen_critical_fact_appendix", "check_qwen_fact_retention",
    "ensure_qwen_critical_fact_appendix", "check_qwen_narrative_retention",
    "ensure_qwen_narrative_appendix", "check_qwen_notebooklm_quality",
]


# ── Time formatting ────────────────────────────────────────────────────────────

def fmt_ts(seconds: float) -> str:
    """Format seconds → HH:MM:SS string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ── Gemini retry delay ─────────────────────────────────────────────────────────

def parse_retry_delay(error: Exception, fallback: int = 65) -> int:
    """Extract suggested wait seconds from a 429 error; return fallback if not found."""
    match = re.search(r'retry in (\d+(?:\.\d+)?)s', str(error), re.IGNORECASE)
    return int(float(match.group(1))) + 10 if match else fallback


# ── Run timestamp extraction ───────────────────────────────────────────────────

def extract_run_ts(path: Path) -> str:
    """Extract YYYYMMDD-HHMMSS run timestamp from a chunk filename.

    Matches the pattern '-YYYYMMDD-HHMMSS.' in the filename.
    Returns '00000000-000000' and prints a warning if not found.
    """
    m = re.search(r'-(\d{8}-\d{6})\.', path.name)
    if not m:
        print(f"[warn] cannot parse run timestamp from: {path.name}", file=sys.stderr)
        return "00000000-000000"
    return m.group(1)


# ── Gemini call wrapper ────────────────────────────────────────────────────────

def call_gemini(
    client,
    parts: list,
    label: str,
    *,
    model: str = "gemini-3.5-flash",
    thinking_budget: int = 4096,
    max_retries: int = 6,
    retry_delay: int = 65,
    max_continuations: int = 20,
    continuation_cooldown: int = 6,
) -> str | None:
    """Call Gemini API with rate-limit retry and MAX_TOKENS auto-continuation.

    Returns the generated text on success, or None if all retries are exhausted.
    Raises ImportError if google-genai is not installed.

    continuation_cooldown: seconds to wait before each "继续" call.
    Free tier allows 10 RPM → minimum 6 s between requests.
    """
    from google.genai import types as _gt  # lazy import — not all callers need Gemini

    config = _gt.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=65536,
        thinking_config=_gt.ThinkingConfig(thinking_budget=thinking_budget),
    )
    gemini_calls = 0
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[{label}] Sending to Gemini ({len(parts)} parts)...", flush=True)
            chat = client.chats.create(model=model, config=config)
            gemini_calls += 1
            response = chat.send_message(parts)
            full_text = response.text
            if not full_text:
                print(f"[{label}] Empty response (content filtered?), not retrying.", flush=True)
                return None

            candidate = response.candidates[0] if response.candidates else None
            for cont in range(max_continuations):
                if not candidate or candidate.finish_reason != _gt.FinishReason.MAX_TOKENS:
                    break
                print(
                    f"[{label}] Output truncated, continuing"
                    f" ({cont + 1}/{max_continuations})...",
                    flush=True,
                )
                time.sleep(continuation_cooldown)  # 10 RPM free tier → 1 req/6 s
                gemini_calls += 1
                # Inner retry: preserve accumulated full_text on 429 mid-continuation.
                # A 429 here must NOT bubble to the outer loop (which recreates the chat).
                # Cap at 3 to prevent max_retries×max_continuations burst on quota exhaustion.
                _cont_retries = min(max_retries, 3)
                for _cr in range(_cont_retries):
                    try:
                        response = chat.send_message("继续")
                        break
                    except Exception as _ce:
                        is_cr = "429" in str(_ce) or "RESOURCE_EXHAUSTED" in str(_ce)
                        if is_cr and _cr < _cont_retries - 1:
                            _cd = parse_retry_delay(_ce, retry_delay)
                            print(f"[{label}] Continuation rate limited, retrying in {_cd}s...", flush=True)
                            time.sleep(_cd)
                        else:
                            raise
                chunk = response.text
                if not chunk:
                    break
                full_text += "\n" + chunk
                candidate = response.candidates[0] if response.candidates else None

            print(
                f"[{label}] Done: {len(full_text):,} chars, {gemini_calls} calls",
                flush=True,
            )
            return full_text

        except Exception as e:
            is_rate = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if not is_rate:
                print(f"[{label}] Non-retriable error: {e}", flush=True)
                return None
            delay = parse_retry_delay(e, retry_delay)
            print(
                f"[{label}] Rate limit: {e}"
                f" — retry in {delay}s ({attempt}/{max_retries})",
                flush=True,
            )
            if attempt < max_retries:
                time.sleep(delay)
    return None


# ── Qwen OpenAI-compatible call wrapper ───────────────────────────────────────

def _part_to_openai_content(part) -> dict:
    """Convert local Gemini-style parts to OpenAI-compatible multimodal content."""
    if isinstance(part, str):
        return {"type": "text", "text": part}

    inline_data = getattr(part, "inline_data", None)
    if inline_data is None:
        raise TypeError(f"Unsupported part type for Qwen adapter: {type(part)!r}")

    data = getattr(inline_data, "data", None)
    mime_type = getattr(inline_data, "mime_type", None) or "image/jpeg"
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"Unsupported inline_data payload for Qwen adapter: {type(data)!r}")

    encoded = base64.b64encode(bytes(data)).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


def _parts_to_openai_messages(parts: list) -> list[dict]:
    content = [_part_to_openai_content(part) for part in parts]
    return [{"role": "user", "content": content}]


def _usage_to_dict(usage) -> dict:
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        total = usage.get("total_tokens") or (prompt + completion)
    else:
        prompt = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", 0) or 0
        total = getattr(usage, "total_tokens", None) or (prompt + completion)
    return {
        "input_tokens": int(prompt),
        "output_tokens": int(completion),
        "total_tokens": int(total),
    }


def _merge_usage(total: dict, current: dict) -> dict:
    return {
        "input_tokens": total.get("input_tokens", 0) + current.get("input_tokens", 0),
        "output_tokens": total.get("output_tokens", 0) + current.get("output_tokens", 0),
        "total_tokens": total.get("total_tokens", 0) + current.get("total_tokens", 0),
    }


def call_qwen(
    client,
    parts: list,
    label: str,
    *,
    model: str = "qwen3.7-plus",
    enable_thinking: bool = False,
    thinking_budget: int = 4096,
    max_retries: int = 2,
    retry_delay: int = 65,
    max_continuations: int = 2,
    continuation_cooldown: int = 2,
    max_tokens: int = 64000,
) -> dict:
    """Call Qwen through Dashscope's OpenAI-compatible chat API.

    Returns a structured result with text, call count, finish reason, and usage.
    The function accepts the same local `parts` shape as `call_gemini`.
    """
    api_calls = 0
    final_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    final_finish_reason = ""
    _error_type = None

    extra_body = {"enable_thinking": enable_thinking}
    if enable_thinking:
        extra_body["thinking_budget"] = thinking_budget

    base_messages = _parts_to_openai_messages(parts)  # encode images once; reuse on retry
    for attempt in range(1, max_retries + 1):
        messages = list(base_messages)
        usage_total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        full_text = ""
        finish_reason = ""
        try:
            print(f"[{label}] Sending to Qwen ({len(parts)} parts)...", flush=True)
            api_calls += 1
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=max_tokens,
                extra_body=extra_body,
            )
            choice = response.choices[0]
            message = choice.message
            chunk = message.content or ""
            if isinstance(chunk, list):
                chunk = "\n".join(str(item) for item in chunk)
            if not chunk:
                print(f"[{label}] Empty initial response (content filtered?), not retrying.", flush=True)
                break

            full_text += str(chunk)
            finish_reason = choice.finish_reason or ""
            usage_total = _merge_usage(usage_total, _usage_to_dict(getattr(response, "usage", None)))

            for cont in range(max_continuations):
                if finish_reason != "length":
                    break
                print(
                    f"[{label}] Output truncated, continuing"
                    f" ({cont + 1}/{max_continuations})...",
                    flush=True,
                )
                messages.append({"role": "assistant", "content": str(chunk)})
                messages.append({"role": "user", "content": "继续"})
                time.sleep(continuation_cooldown)

                api_calls += 1
                # Inner retry: preserve accumulated full_text on 429 mid-continuation.
                _cont_retries = min(max_retries, 3)
                for _cr in range(_cont_retries):
                    try:
                        response = client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=0.1,
                            max_tokens=max_tokens,
                            extra_body=extra_body,
                        )
                        break
                    except Exception as _ce:
                        is_cr = "429" in str(_ce) or "rate" in str(_ce).lower() or "throttl" in str(_ce).lower()
                        if is_cr and _cr < _cont_retries - 1:
                            _cd = parse_retry_delay(_ce, retry_delay)
                            print(f"[{label}] Continuation rate limited, retrying in {_cd}s...", flush=True)
                            time.sleep(_cd)
                        else:
                            raise
                choice = response.choices[0]
                message = choice.message
                chunk = message.content or ""
                if isinstance(chunk, list):
                    chunk = "\n".join(str(item) for item in chunk)
                if not chunk:
                    print(f"[{label}] Continuation {cont + 1} returned empty chunk — stopping.", flush=True)
                    break
                full_text += "\n" + str(chunk)
                finish_reason = choice.finish_reason or ""
                usage_total = _merge_usage(usage_total, _usage_to_dict(getattr(response, "usage", None)))

            print(
                f"[{label}] Done: {len(full_text):,} chars, {api_calls} calls"
                f", finish_reason={finish_reason or 'unknown'}",
                flush=True,
            )
            return {
                "text": full_text,
                "provider": "qwen",
                "model": model,
                "api_calls": api_calls,
                "finish_reason": finish_reason,
                "usage": usage_total,
                "estimated_cost_cny": None,
            }

        except Exception as e:
            final_usage = usage_total
            final_finish_reason = finish_reason
            err_str = str(e).lower()
            is_rate = "429" in err_str or "rate" in err_str or "throttl" in err_str
            if not is_rate:
                if "datainspection" in err_str or "data_inspection" in err_str:
                    _error_type = "data_inspection_failed"
                print(f"[{label}] Non-retriable error: {e}", flush=True)
                break
            delay = parse_retry_delay(e, retry_delay)
            print(
                f"[{label}] Rate limit: {e}"
                f" — retry in {delay}s ({attempt}/{max_retries})",
                flush=True,
            )
            if attempt < max_retries:
                time.sleep(delay)

    return {
        "text": None,
        "provider": "qwen",
        "model": model,
        "api_calls": api_calls,
        "finish_reason": final_finish_reason,
        "usage": final_usage,
        "estimated_cost_cny": None,
        "error": _error_type,
    }


# ── Qwen output QC ─────────────────────────────────────────────────────────────
# Extracted from scripts/build_stream_markdown.py so run_dual_model.py and other
# callers can use the same QC logic without importing the stream synthesis script.

QWEN_BODY_MIN_TRANSCRIPT_RATIO = 0.20
QWEN_FACT_RETENTION_MIN_RATIO = 0.90
QWEN_NARRATIVE_RETENTION_MIN_RATIO = 0.32
QWEN_NARRATIVE_MIN_BLOCKS_PER_WINDOW = 2

QWEN_CRITICAL_FACT_TERMS = [
    "75分", "所见即所得", "不要替换", "34岁", "2017年", "年终奖", "99.9%",
    "4万积分", "19.9万积分", "30万积分", "15秒", "30秒", "1分钟", "3分钟",
    "Remotion", "HyperFrames", "Coze", "扣子", "Context Compression", "即梦", "Dreamina", "FDE",
]


def _context_snippet(text: str, needle: str, radius: int = 80) -> str:
    idx = text.find(needle)
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    return re.sub(r'\s+', ' ', text[start:end]).strip()


def _fact_aliases(value: str) -> list[str]:
    aliases = [value]
    if value == "Coze":
        aliases.append("扣子")
    elif value == "扣子":
        aliases.append("Coze")
    elif value == "Context Compression":
        aliases.extend(["上下文压缩", "CC"])
    elif value == "Dreamina":
        aliases.append("即梦")
    elif value == "即梦":
        aliases.append("Dreamina")
    elif value == "75分":
        aliases.extend(["75 分", "75"])
    elif value == "99.9%":
        aliases.append("99.9％")
    elif value == "4万积分":
        aliases.append("4 万积分")
    elif value == "19.9万积分":
        aliases.append("19.9 万积分")
    elif value == "30万积分":
        aliases.append("30 万积分")
    return list(dict.fromkeys(aliases))


def _strip_markdown_noise(text: str) -> str:
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    text = re.sub(r'(?m)^#{1,6}\s+', '', text)
    text = re.sub(r'(?m)^\s*[-*]\s+', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _narrative_anchor(text: str) -> str:
    return _strip_markdown_noise(text)[:80]


def extract_qwen_critical_facts(note_texts: list[str]) -> list[dict]:
    """Deterministically extract must-retain facts from Qwen window notes."""
    facts: list[dict] = []
    seen: set[str] = set()

    def add_fact(kind: str, value: str, window_index: int, source_text: str) -> None:
        value = value.strip()
        if not value:
            return
        key = re.sub(r'\s+', '', value.lower())
        if key in seen:
            return
        seen.add(key)
        facts.append({
            "kind": kind,
            "value": value,
            "aliases": _fact_aliases(value),
            "window_index": window_index,
            "context": _context_snippet(source_text, value),
        })

    for idx, text in enumerate(note_texts, start=1):
        for term in QWEN_CRITICAL_FACT_TERMS:
            if term in text:
                kind = "term"
                if term.endswith("分"):
                    kind = "score"
                elif term.endswith("积分"):
                    kind = "cost"
                elif term.endswith("年") or term.endswith("岁"):
                    kind = "date_or_age"
                elif term in {"所见即所得", "不要替换"}:
                    kind = "prompt_keyword"
                elif term in {"Remotion", "HyperFrames", "Coze", "扣子", "Context Compression", "即梦", "Dreamina", "FDE"}:
                    kind = "tool_or_concept"
                add_fact(kind, term, idx, text)

        for pattern, kind in [
            (r'\d+(?:\.\d+)?\s*%', "percentage"),
            (r'\d+(?:\.\d+)?\s*分(?!钟)', "score"),
            (r'\d+(?:\.\d+)?\s*万?\s*积分', "cost"),
            (r'20\d{2}年', "date_or_age"),
            (r'\d+\s*岁', "date_or_age"),
        ]:
            for m in re.finditer(pattern, text):
                add_fact(kind, re.sub(r'\s+', '', m.group(0)), idx, text)

    return facts


def extract_qwen_narrative_blocks(note_texts: list[str]) -> list[dict]:
    """Extract long narrative evidence blocks from Qwen window notes."""
    blocks: list[dict] = []
    seen: set[str] = set()

    def add_block(window_index: int, title: str, body: str, time_range: str = "") -> None:
        cleaned = _strip_markdown_noise(body)
        if len(cleaned) < 180:
            return
        key = cleaned[:120]
        if key in seen:
            return
        seen.add(key)
        blocks.append({
            "window_index": window_index,
            "title": title.strip() or f"Window {window_index} narrative evidence",
            "time_range": time_range.strip(),
            "chars": len(cleaned),
            "anchor": _narrative_anchor(cleaned),
            "text": cleaned,
        })

    for window_index, note in enumerate(note_texts, start=1):
        section_match = re.search(
            r'(?ims)^##\s+Narrative Evidence Blocks\s*(.*?)(?=^##\s+|\Z)',
            note,
        )
        if section_match:
            section = section_match.group(1).strip()
            matches = list(re.finditer(
                r'(?ims)^###\s+Narrative Block\s*(?:\[(.*?)\])?\s*(.*?)\n(.*?)(?=^###\s+Narrative Block|\Z)',
                section,
            ))
            if matches:
                for m in matches:
                    add_block(window_index, m.group(2), m.group(3), m.group(1) or "")
            else:
                for i, para in enumerate(re.split(r'\n\s*\n+', section), start=1):
                    add_block(window_index, f"Narrative block {i}", para)
            continue

        faithful = re.search(
            r'(?ims)^##\s+Faithful Notes\s*(.*?)(?=^##\s+Preserved Prompts|^##\s+Visual Evidence|^##\s+Quotes|^##\s+Merge Hints|\Z)',
            note,
        )
        fallback = faithful.group(1) if faithful else note
        candidates = re.split(r'\n\s*\n+', fallback)
        added = 0
        for i, para in enumerate(candidates, start=1):
            if added >= QWEN_NARRATIVE_MIN_BLOCKS_PER_WINDOW:
                break
            if any(marker in para for marker in ["```", "Window Metadata", "Preserved Prompts"]):
                continue
            before = len(blocks)
            add_block(window_index, f"Fallback narrative block {i}", para)
            if len(blocks) > before:
                added += 1

    return blocks


def format_qwen_critical_facts_for_prompt(facts: list[dict]) -> str:
    """Format extracted critical facts as a checklist for injection into the assembly prompt."""
    if not facts:
        return "## Critical Facts Checklist\n\n未从窗口笔记中检测到必须保留的关键事实。\n"
    lines = [
        "## Critical Facts Checklist",
        "",
        "以下事实由程序从 Qwen window notes 中确定性抽取。最终 Markdown 必须逐项保留；"
        "可在正文或 `## 5. 技术资产附录：Prompts / Code / Config` 中落地。",
        "",
    ]
    for i, fact in enumerate(facts, start=1):
        aliases = ", ".join(fact.get("aliases") or [fact["value"]])
        context = fact.get("context", "")
        lines.append(
            f"{i}. [{fact['kind']}] `{fact['value']}`"
            f" | aliases: {aliases}"
            f" | source window: {fact['window_index']}"
        )
        if context:
            lines.append(f"   - context: {context}")
    return "\n".join(lines) + "\n"


def format_qwen_narrative_blocks_for_prompt(blocks: list[dict]) -> str:
    """Format extracted narrative blocks for injection into the assembly prompt."""
    if not blocks:
        return "## Narrative Evidence Blocks\n\n未从窗口笔记中检测到长叙事证据块。\n"
    lines = [
        "## Narrative Evidence Blocks",
        "",
        "以下长叙事证据由程序从 Qwen window notes 中抽取。最终 Markdown 必须吸收其细节，"
        "并在正文或 `## 6. 叙事证据附录` 中保留。不要压缩成思维导图短句。",
        "",
    ]
    for i, block in enumerate(blocks, start=1):
        time_part = f" [{block['time_range']}]" if block.get("time_range") else ""
        lines.append(
            f"### Narrative Evidence {i}{time_part}"
            f" - {block['title']} (window {block['window_index']})"
        )
        lines.append(block["text"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def format_qwen_critical_fact_appendix(facts: list[dict]) -> str:
    if not facts:
        return ""
    lines = [
        "## 7. 关键事实索引",
        "",
        "> 以下索引由程序从 Qwen window notes 确定性生成，用于避免关键数字、年份、评分、时长和工具名在最终组装时被压缩丢失。",
        "",
        "| # | 类型 | 事实 | 来源窗口 | 上下文 |",
        "|---|---|---|---:|---|",
    ]
    for idx, fact in enumerate(facts, start=1):
        context = _strip_markdown_noise(str(fact.get("context", ""))).replace("|", " / ")
        if len(context) > 180:
            context = context[:177].rstrip() + "..."
        value = str(fact.get("value", "")).replace("|", " / ")
        kind = str(fact.get("kind", "")).replace("|", " / ")
        window_index = fact.get("window_index", "")
        lines.append(f"| {idx} | {kind} | {value} | {window_index} | {context} |")
    return "\n".join(lines).strip() + "\n"


def check_qwen_fact_retention(markdown_body: str, facts: list[dict]) -> dict:
    if not facts:
        return {"warnings": [], "metrics": {"fact_count": 0, "retained_count": 0, "retention_ratio": 1.0, "missing_facts": []}}

    missing = []
    retained = 0
    for fact in facts:
        aliases = fact.get("aliases") or [fact["value"]]
        if any(alias and alias in markdown_body for alias in aliases):
            retained += 1
        else:
            missing.append({"kind": fact["kind"], "value": fact["value"], "window_index": fact.get("window_index")})
    ratio = retained / max(1, len(facts))
    warnings = []
    if missing:
        warnings.append(
            "qwen_critical_facts_missing: "
            + ", ".join(f"{m['value']}(w{m['window_index']})" for m in missing[:20])
        )
    if ratio < QWEN_FACT_RETENTION_MIN_RATIO:
        warnings.append(
            f"qwen_fact_retention_low: retained {retained}/{len(facts)}"
            f" ({ratio:.2f}), expected >= {QWEN_FACT_RETENTION_MIN_RATIO:.2f}"
        )
    return {
        "warnings": warnings,
        "metrics": {
            "fact_count": len(facts),
            "retained_count": retained,
            "retention_ratio": round(ratio, 4),
            "missing_facts": missing,
            "min_retention_ratio": QWEN_FACT_RETENTION_MIN_RATIO,
        },
    }


def ensure_qwen_critical_fact_appendix(markdown_body: str, facts: list[dict]) -> tuple[str, dict]:
    if not facts:
        return markdown_body, {"appended": False, "reason": "no_facts", "appended_facts": 0}
    if "## 7. 关键事实索引" in markdown_body or "## 关键事实索引" in markdown_body:
        retention = check_qwen_fact_retention(markdown_body, facts)
        if not retention["metrics"]["missing_facts"]:
            return markdown_body, {
                "appended": False,
                "reason": "already_present",
                "appended_facts": 0,
                "source_metrics": retention["metrics"],
            }

    marker = "<!-- qwen_window_coverage:"
    coverage_tail = ""
    body = markdown_body.rstrip()
    if marker in body:
        idx = body.rfind(marker)
        coverage_tail = body[idx:].strip()
        body = body[:idx].rstrip()

    appendix = format_qwen_critical_fact_appendix(facts)
    if "## 7. 关键事实索引" in body or "## 关键事实索引" in body:
        appendix = appendix.replace("## 7. 关键事实索引", "## 7. 关键事实索引（程序补全）", 1)
    updated = body + "\n\n" + appendix.rstrip() + "\n"
    if coverage_tail:
        updated += "\n" + coverage_tail + "\n"
    retention = check_qwen_fact_retention(updated, facts)
    return updated, {
        "appended": True,
        "reason": "deterministic_source_retention",
        "appended_facts": len(facts),
        "source_metrics": retention["metrics"],
    }


def check_qwen_narrative_retention(markdown_body: str, blocks: list[dict], transcript: str) -> dict:
    transcript_chars = max(1, len(transcript.strip()))
    body_chars = len(markdown_body.strip())
    body_ratio = body_chars / transcript_chars

    if not blocks:
        return {
            "warnings": ["qwen_narrative_blocks_missing: no narrative evidence blocks extracted"],
            "metrics": {
                "narrative_block_count": 0,
                "retained_block_count": 0,
                "retention_ratio": 0,
                "body_transcript_ratio": round(body_ratio, 4),
                "min_body_transcript_ratio": QWEN_NARRATIVE_RETENTION_MIN_RATIO,
                "missing_blocks": [],
            },
        }

    missing = []
    retained = 0
    for block in blocks:
        anchor = block.get("anchor", "")
        text = block.get("text", "")
        probes = [anchor[:50], anchor[:35], text[:80], text[:50]]
        if any(probe and probe in markdown_body for probe in probes):
            retained += 1
        else:
            missing.append({
                "window_index": block.get("window_index"),
                "title": block.get("title"),
                "anchor": anchor[:80],
            })
    retention_ratio = retained / max(1, len(blocks))
    warnings = []
    if body_ratio < QWEN_NARRATIVE_RETENTION_MIN_RATIO:
        warnings.append(
            f"qwen_narrative_body_ratio_low: body/transcript ratio {body_ratio:.2f},"
            f" expected >= {QWEN_NARRATIVE_RETENTION_MIN_RATIO:.2f}"
        )
    if missing:
        warnings.append(
            "qwen_narrative_blocks_missing_from_final: "
            + ", ".join(f"w{m['window_index']}:{m['title']}" for m in missing[:10])
        )
    return {
        "warnings": warnings,
        "metrics": {
            "narrative_block_count": len(blocks),
            "retained_block_count": retained,
            "retention_ratio": round(retention_ratio, 4),
            "body_transcript_ratio": round(body_ratio, 4),
            "min_body_transcript_ratio": QWEN_NARRATIVE_RETENTION_MIN_RATIO,
            "missing_blocks": missing,
        },
    }


def ensure_qwen_narrative_appendix(markdown_body: str, blocks: list[dict], transcript: str) -> tuple[str, dict]:
    """Deterministically append narrative evidence if final assembly compresses it."""
    if not blocks:
        return markdown_body, {"appended": False, "reason": "no_blocks", "appended_blocks": 0}

    retention = check_qwen_narrative_retention(markdown_body, blocks, transcript)
    metrics = retention["metrics"]
    has_section = "## 6. 叙事证据附录" in markdown_body or "## 叙事证据附录" in markdown_body
    # Only append when section is completely absent. If the section header already
    # exists (even if thin), appending again creates a duplicate ## 6 heading.
    # Low-ratio cases are addressed by prompt improvement, not structural duplication.
    should_append = not has_section
    if not should_append:
        return markdown_body, {"appended": False, "reason": "already_retained", "appended_blocks": 0}

    marker = "<!-- qwen_window_coverage:"
    coverage_tail = ""
    body = markdown_body.rstrip()
    if marker in body:
        idx = body.rfind(marker)
        coverage_tail = body[idx:].strip()
        body = body[:idx].rstrip()

    lines = [
        "",
        "## 6. 叙事证据附录",
        "",
        "> 以下内容由程序从 Qwen window notes 确定性追加，用于避免长文叙事在最终组装时被压缩丢失。",
        "",
    ]
    for i, block in enumerate(blocks, start=1):
        time_part = f" [{block['time_range']}]" if block.get("time_range") else ""
        lines.append(f"### Narrative Evidence {i}{time_part} - {block['title']} (window {block['window_index']})")
        lines.append(block["text"])
        lines.append("")
    if coverage_tail:
        lines.append(coverage_tail)
    return body + "\n" + "\n".join(lines).rstrip() + "\n", {
        "appended": True,
        "reason": "missing_or_low_retention",
        "appended_blocks": len(blocks),
        "pre_append_metrics": metrics,
    }


def check_qwen_notebooklm_quality(markdown_body: str, transcript: str, manifest: dict) -> dict:
    """Detect Qwen outputs that are too compressed for NotebookLM source use."""
    body = markdown_body.strip()
    transcript_chars = max(1, len(transcript.strip()))
    body_chars = len(body)
    body_ratio = body_chars / transcript_chars

    h1_exists = bool(re.search(r'(?m)^#\s+[^#\s].+', body))
    required_sections = ["## 1. 视频元数据", "## 2. 核心知识字典", "## 3. 详尽内容解析"]
    missing_sections = [s for s in required_sections if s not in body]
    chapter_count = len(re.findall(r'(?m)^###\s+\[\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}\]', body))
    field_names = ["**核心论点：**", "**详细展开：**", "**视觉/屏幕内容：**", "**重要金句/原话：**"]
    missing_chapter_fields = [name for name in field_names if chapter_count and name not in body]

    code_fence_count = body.count("```")
    source_prompt_markers = ["Prompt", "prompt", "提示词", "所见即所得", "不要替换", "配置", "代码"]
    source_has_prompt_like_detail = any(marker in transcript for marker in source_prompt_markers)
    missing_prompt_markers = [
        marker for marker in ["提示词", "所见即所得", "不要替换"]
        if marker in transcript and marker not in body
    ]

    warnings: list[str] = []
    if not h1_exists:
        warnings.append("qwen_missing_h1: final body must start with a concrete H1 title")
    if missing_sections:
        warnings.append("qwen_missing_required_sections: " + ", ".join(missing_sections))
    if chapter_count == 0:
        warnings.append("qwen_missing_timestamped_chapters: no ### [HH:MM:SS - HH:MM:SS] chapters found")
    if missing_chapter_fields:
        warnings.append("qwen_missing_chapter_fields: " + ", ".join(missing_chapter_fields))
    if body_ratio < QWEN_BODY_MIN_TRANSCRIPT_RATIO:
        warnings.append(
            f"qwen_overcompressed_body: body/transcript ratio {body_ratio:.2f},"
            f" expected >= {QWEN_BODY_MIN_TRANSCRIPT_RATIO:.2f}"
        )
    if source_has_prompt_like_detail and code_fence_count < 2:
        warnings.append(
            "qwen_missing_code_blocks: source contains prompt/config/code-like details"
            " but model body has no fenced code block"
        )
    if missing_prompt_markers:
        warnings.append("qwen_missing_prompt_keywords: " + ", ".join(missing_prompt_markers))

    return {
        "warnings": warnings,
        "metrics": {
            "h1_exists": h1_exists,
            "body_chars": body_chars,
            "body_transcript_ratio": round(body_ratio, 4),
            "required_sections_missing": missing_sections,
            "timestamped_chapter_count": chapter_count,
            "chapter_fields_missing": missing_chapter_fields,
            "code_fence_count": code_fence_count,
            "prompt_keywords_missing": missing_prompt_markers,
            "body_min_transcript_ratio": QWEN_BODY_MIN_TRANSCRIPT_RATIO,
            "source_frame_count": manifest.get("frame_count", 0),
        },
    }

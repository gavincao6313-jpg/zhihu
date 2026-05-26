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

__all__ = ["fmt_ts", "parse_retry_delay", "extract_run_ts", "call_gemini", "call_qwen"]


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
                raise RuntimeError("Gemini returned empty response")

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
                for _cr in range(max_retries):
                    try:
                        response = chat.send_message("继续")
                        break
                    except Exception as _ce:
                        is_cr = "429" in str(_ce) or "RESOURCE_EXHAUSTED" in str(_ce)
                        if is_cr and _cr < max_retries - 1:
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
            delay = parse_retry_delay(e, retry_delay) if is_rate else retry_delay
            print(
                f"[{label}] {'Rate limit' if is_rate else 'Error'}: {e}"
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
    model: str = "qwen3.6-flash",
    enable_thinking: bool = False,
    thinking_budget: int = 4096,
    max_retries: int = 2,
    retry_delay: int = 10,
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

    extra_body = {"enable_thinking": enable_thinking}
    if enable_thinking:
        extra_body["thinking_budget"] = thinking_budget

    for attempt in range(1, max_retries + 1):
        messages = _parts_to_openai_messages(parts)
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
                raise RuntimeError("Qwen returned empty response")

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
            is_rate = "429" in str(e) or "rate" in str(e).lower() or "throttl" in str(e).lower()
            delay = parse_retry_delay(e, retry_delay) if is_rate else retry_delay
            print(
                f"[{label}] {'Rate limit' if is_rate else 'Error'}: {e}"
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
    }

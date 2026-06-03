import type { RunPlan, RunPlanRequest, RunRecord } from "./types";

const sampleRun: RunRecord = {
  id: "live_20260601_medical_ai",
  base: "live_20260601_医疗行业AI转型一应用",
  source_type: "live",
  status: "completed",
  created_at: "2026-06-01T20:01:48+08:00",
  updated_at: "2026-06-01T22:50:14+08:00",
  provider: "qwen",
  model: "qwen3.6-plus",
  synthesis_pass: "sliding-window",
  paths: {
    manifest_json: "runs/stream-live_20260601_医疗行业AI转型一应用-20260601-225014.manifest.json",
    final_qc: "runs/stream-live_20260601_医疗行业AI转型一应用-20260601-225004.qwen-full.final-qc.json",
    markdown: "Markdowns/TTS_stream-live_20260601_医疗行业AI转型一应用-qwen-full.md"
  },
  metrics: {
    chunks: 170,
    transcript_chars: 51551,
    frames: 436,
    warnings: 2
  },
  steps: [
    { key: "source", label: "Source", status: "done", summary: "Live URL captured through Playwright keepalive" },
    { key: "record", label: "Capture", status: "done", summary: "170 chunks recorded and indexed" },
    { key: "transcript", label: "Transcript", status: "done", summary: "51,551 characters merged" },
    { key: "frames", label: "Keyframes", status: "done", summary: "436 visual evidence frames" },
    { key: "synthesis", label: "Synthesis", status: "warning", summary: "Qwen sliding-window with 2 warnings" },
    { key: "markdown", label: "Markdown", status: "done", summary: "Final NotebookLM document available" }
  ],
  chunks: [
    { index: 1, start_s: 0, duration_s: 60, transcript_chars: 286, segments: 8, frames: 3, reextracts: 0, backend: "SenseVoice" },
    { index: 84, start_s: 5013, duration_s: 60, transcript_chars: 412, segments: 11, frames: 4, reextracts: 0, backend: "SenseVoice" },
    { index: 166, start_s: 9965, duration_s: 60, transcript_chars: 198, segments: 6, frames: 2, reextracts: 0, backend: "SenseVoice" }
  ],
  frames: [
    { timestamp_s: 1, type: "slide", path: "runs/.../chunk001.payload.json", chunk_index: 1, selected: true },
    { timestamp_s: 4348, type: "annotation", path: "runs/.../chunk073.payload.json", chunk_index: 73, selected: true },
    { timestamp_s: 8093, type: "context", path: "runs/.../chunk135.payload.json", chunk_index: 135, selected: true }
  ],
  qc: {
    source_status: "full",
    body_coverage_status: "ok",
    body_tail_gap_s: 44,
    frame_count: 436,
    warnings: [
      "qwen_missing_prompt_keywords: 提示词",
      "qwen_narrative_blocks_missing_from_final: w3"
    ],
    provider: "qwen",
    model: "qwen3.6-plus",
    synthesis_pass: "sliding-window",
    qwen_window_policy: {
      window_count: 3,
      total_frames: 436,
      covered_new_frames: 436,
      overlap_frames: 80,
      dropped_frames: 0
    }
  },
  transcript_preview: "完整逐字稿将在 API server 接入后从 runs/*.combined-transcript.txt 读取。",
  markdown_preview: "# 医疗行业 AI 转型一应用\n\n最终 Markdown 预览将在 API server 接入后从 Markdowns/*.md 读取。"
};

function isServerDown(error: unknown): boolean {
  return error instanceof TypeError && String(error).includes("Failed to fetch");
}

export interface ServerConfig {
  launch_mode: "simulate" | "live";
  readonly: boolean;
  running_statuses: string[];
}

export interface AuthStatus {
  ok: boolean;
  message: string;
  detail: Record<string, string>;
}

export async function fetchAuthStatus(platform?: string, url?: string): Promise<AuthStatus> {
  try {
    let query = `/api/check-auth`;
    const params = new URLSearchParams();
    if (platform) params.set("platform", platform);
    if (url) params.set("url", url);
    const qs = params.toString();
    if (qs) query += `?${qs}`;
    const response = await fetch(query);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return (await response.json()) as AuthStatus;
  } catch {
    return { ok: false, message: "无法连接 API 服务器", detail: {} };
  }
}

export async function fetchConfig(): Promise<ServerConfig> {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return (await response.json()) as ServerConfig;
  } catch {
    return { launch_mode: "simulate", readonly: false, running_statuses: [] };
  }
}

export async function fetchRuns(): Promise<RunRecord[]> {
  try {
    const response = await fetch("/api/runs");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = (await response.json()) as RunRecord[];
    return data.length ? data : [sampleRun];
  } catch (error) {
    // Fall back to sample data only when the API server is not running yet.
    if (isServerDown(error)) return [sampleRun];
    throw error;
  }
}

export async function fetchRun(id: string): Promise<RunRecord> {
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return (await response.json()) as RunRecord;
  } catch (error) {
    if (isServerDown(error)) return sampleRun;
    throw error;
  }
}

export async function createRunPlan(request: RunPlanRequest): Promise<RunPlan> {
  const response = await fetch("/api/run-plans", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as RunPlan;
}

export async function createRun(request: RunPlanRequest): Promise<RunRecord> {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  });
  if (!response.ok) {
    let msg = `HTTP ${response.status}`;
    try { msg = ((await response.json()) as { error?: string }).error ?? msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await response.json()) as RunRecord;
}

export async function launchRun(id: string): Promise<RunRecord> {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}/launch`, { method: "POST" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as RunRecord;
}

export async function patchRun(id: string, status: string, message: string): Promise<RunRecord> {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, message }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as RunRecord;
}

export async function fetchLiveChunks(
  id: string,
): Promise<{ base: string; chunk_count: number; chunks: import("./types").ChunkRecord[] }> {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}/live-chunks`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

// Statuses that require frontend polling (kept in sync with server RUNNING_STATUSES).
// "created" included so directLaunch() polls immediately after launchRun() returns.
export const RUNNING_STATUSES = new Set(["created", "probing", "recording", "transcribing", "synthesizing"]);

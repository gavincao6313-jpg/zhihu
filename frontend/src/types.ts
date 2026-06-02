export type SourceType = "mp4" | "replay" | "live";
export type RunStatus = "created" | "probing" | "recording" | "transcribing" | "synthesizing" | "completed" | "warning" | "failed";

export interface ArtifactPathMap {
  manifest_json?: string;
  manifest_md?: string;
  combined_transcript?: string;
  final_qc?: string;
  markdown?: string;
  slides_pdf?: string;
}

export interface RunMetrics {
  chunks: number;
  transcript_chars: number;
  frames: number;
  warnings: number;
}

export interface PipelineStep {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "warning" | "failed";
  summary: string;
  artifacts?: string[];
}

export interface ChunkRecord {
  index: number;
  start_s: number;
  duration_s: number;
  transcript_chars: number;
  segments: number;
  frames: number;
  reextracts: number;
  backend: string;
  report_path?: string;
  transcript_path?: string;
  payload_path?: string;
}

export interface FrameRecord {
  timestamp_s: number;
  type: "slide" | "annotation" | "context";
  path: string;
  chunk_index?: number;
  selected?: boolean;
}

export interface QcSummary {
  source_status?: string;
  body_coverage_status?: string;
  body_tail_gap_s?: number;
  frame_count?: number;
  warnings: string[];
  provider?: string;
  model?: string;
  synthesis_pass?: string;
  qwen_window_policy?: {
    window_count?: number;
    covered_new_frames?: number;
    total_frames?: number;
    overlap_frames?: number;
    dropped_frames?: number;
  };
}

export interface RunRecord {
  id: string;
  base: string;
  source_type: SourceType;
  status: RunStatus;
  created_at?: string;
  updated_at?: string;
  provider?: string;
  model?: string;
  synthesis_pass?: string;
  label?: string;
  paths: ArtifactPathMap;
  metrics: RunMetrics;
  steps: PipelineStep[];
  chunks: ChunkRecord[];
  frames: FrameRecord[];
  qc?: QcSummary;
  plan?: RunPlan | null;
  logs?: RunLogEntry[];
  transcript_preview?: string;
  markdown_preview?: string;
}

export interface RunLogEntry {
  time: string;
  level: "info" | "warning" | "error";
  message: string;
}

export interface RunPlanCommand {
  stage: string;
  label: string;
  command: string;
  summary: string;
}

export interface RunPlanCheck {
  key: string;
  status: "ok" | "warning" | "failed";
  summary: string;
}

export interface RunPlanRequest {
  source_type: SourceType;
  source: string;
  base?: string;
  provider: "gemini" | "qwen";
  synthesis_pass: "one-shot" | "sliding-window";
  qwen_max_frames: number;
}

export interface RunPlan {
  id: string;
  dry_run: boolean;
  created_at: string;
  source_type: SourceType;
  source: string;
  base: string;
  provider: string;
  synthesis_pass: string;
  qwen_max_frames: number;
  warnings: string[];
  checks: RunPlanCheck[];
  commands: RunPlanCommand[];
  paths: ArtifactPathMap;
}

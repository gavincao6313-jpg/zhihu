import { useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Boxes,
  CheckCircle2,
  CirclePlay,
  FileText,
  Film,
  Gauge,
  Image as ImageIcon,
  Play,
  Radio,
  RefreshCw,
  Search,
  Terminal,
  Upload,
  Video,
} from "lucide-react";
import {
  RUNNING_STATUSES,
  createRun,
  createRunPlan,
  fetchAuthStatus,
  fetchConfig,
  fetchLiveChunks,
  fetchRun,
  fetchRuns,
  launchRun,
} from "./api";
import type { AuthStatus, ServerConfig } from "./api";
import { useWorkerInterval } from "./useWorkerInterval";
import type { Lang } from "./i18n";
import { t } from "./i18n";
import type { RunPlan, RunPlanRequest, RunRecord, SourceType } from "./types";

// ── Static lookup tables ──────────────────────────────────────────────────────

const SOURCE_ICONS: Record<SourceType, typeof Film> = {
  mp4: Film,
  replay: Video,
  live: Radio,
};

const SOURCE_LABELS: Record<SourceType, { zh: string; en: string }> = {
  mp4:    { zh: "MP4",  en: "MP4" },
  replay: { zh: "回放", en: "Replay" },
  live:   { zh: "直播", en: "Live" },
};

const STATUS_LABELS: Record<string, { zh: string; en: string }> = {
  created:      { zh: "已创建",  en: "created" },
  probing:      { zh: "检测中",  en: "probing" },
  recording:    { zh: "录制中",  en: "recording" },
  transcribing: { zh: "转写中",  en: "transcribing" },
  synthesizing: { zh: "合成中",  en: "synthesizing" },
  completed:    { zh: "完成",    en: "completed" },
  warning:      { zh: "警告",    en: "warning" },
  failed:       { zh: "失败",    en: "failed" },
};

const STEP_LABELS: Record<string, { zh: string; en: string }> = {
  source:     { zh: "来源",     en: "Source" },
  record:     { zh: "采集",     en: "Capture" },
  transcript: { zh: "转写",     en: "Transcript" },
  frames:     { zh: "关键帧",   en: "Keyframes" },
  qc:         { zh: "质检",     en: "QC" },
  markdown:   { zh: "Markdown", en: "Markdown" },
  synthesis:  { zh: "合成",     en: "Synthesis" },
  process:    { zh: "处理",     en: "Process" },
};

const TAB_LABELS = {
  Overview:   { zh: "概览",    en: "Overview" },
  Plan:       { zh: "计划",    en: "Plan" },
  Logs:       { zh: "日志",    en: "Logs" },
  Chunks:     { zh: "分片",    en: "Chunks" },
  QC:         { zh: "质检",    en: "QC" },
  Keyframes:  { zh: "关键帧",  en: "Keyframes" },
  Transcript: { zh: "逐字稿",  en: "Transcript" },
  Markdown:   { zh: "Markdown",en: "Markdown" },
} as const;

const tabs = [
  "Overview", "Plan", "Logs", "Chunks", "QC", "Keyframes", "Transcript", "Markdown",
] as const;
type Tab = (typeof tabs)[number];

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatSeconds(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return [h, m, s].map((p) => String(p).padStart(2, "0")).join(":");
}

function statusLabel(status: string, lang: Lang): string {
  return STATUS_LABELS[status]?.[lang] ?? status.replace("_", " ");
}

function stepLabel(key: string, serverLabel: string, lang: Lang): string {
  return STEP_LABELS[key]?.[lang] ?? serverLabel;
}

const _STEP_SUMMARY_ZH: Record<string, string> = {
  "Not started": "未开始",
  "Waiting for capture output": "等待采集输出",
  "Waiting for payload frames": "等待载荷帧",
  "No final QC yet": "暂无质检结果",
  "Combined transcript available": "逐字稿已就绪",
  "No combined transcript": "暂无逐字稿",
  "Final Markdown available": "Markdown 已就绪",
  "No final Markdown": "暂无 Markdown",
  "Live capture active": "直播采集中",
};

const _SOURCE_TYPE_ZH: Record<string, string> = { replay: "回放", live: "直播", mp4: "MP4" };

const _STAGE_LABELS_ZH: Record<string, { zh: string; en: string }> = {
  PREPARE:    { zh: "准备",   en: "PREPARE" },
  SYNTHESIZE: { zh: "合成",   en: "SYNTHESIZE" },
  CAPTURE:    { zh: "采集",   en: "CAPTURE" },
  TRANSCRIBE: { zh: "转写",   en: "TRANSCRIBE" },
  RUN:        { zh: "运行",   en: "RUN" },
};

const _PATH_KEY_ZH: Record<string, { zh: string; en: string }> = {
  MANIFEST_JSON:       { zh: "manifest 清单",  en: "manifest json" },
  COMBINED_TRANSCRIPT: { zh: "合并逐字稿",      en: "combined transcript" },
  FINAL_QC:            { zh: "质检报告",        en: "final qc" },
  MARKDOWN:            { zh: "最终 Markdown",   en: "markdown" },
  MP4_PATH:            { zh: "MP4 路径",        en: "mp4 path" },
};

function stepSummary(summary: string, lang: Lang): string {
  if (lang === "en" || !summary) return summary;
  if (_STEP_SUMMARY_ZH[summary]) return _STEP_SUMMARY_ZH[summary];
  let m: RegExpMatchArray | null;
  if ((m = summary.match(/^(\d+) planned commands?$/))) return `${m[1]} 个计划命令`;
  if ((m = summary.match(/^(\d+) chunks? indexed$/))) return `${m[1]} 个分片已索引`;
  if ((m = summary.match(/^(\d+) frames? in QC$/))) return `${m[1]} 帧已质检`;
  if ((m = summary.match(/^(\d+) warnings?, coverage=(.+)$/))) return `${m[1]} 个警告，覆盖率=${m[2]}`;
  if ((m = summary.match(/^source_status=(.+)$/))) return `来源状态=${qcStatusValue(m[1], lang)}`;
  if ((m = summary.match(/^(\w+) input planned$/))) return `${_SOURCE_TYPE_ZH[m[1]] ?? m[1]} 输入已计划`;
  return summary;
}

function qcStatusValue(value: string | number | null | undefined, lang: Lang): string {
  if (value == null) return "-";
  if (lang === "en") return String(value);
  const zh: Record<string, string> = {
    planned: "计划中", pending: "待处理", unknown: "未知",
    ok: "正常", failed: "失败", partial: "部分", full: "完整",
    warning: "警告", completed: "完成",
  };
  return zh[String(value)] ?? String(value);
}

function localizeWarning(w: string, lang: Lang): string {
  if (lang === "en") return w;
  const sep = w.indexOf(": ");
  const key = sep >= 0 ? w.slice(0, sep) : w;
  const detail = sep >= 0 ? w.slice(sep + 2) : "";
  const keyZh: Record<string, string> = {
    body_tail_coverage_low:                   "正文尾部覆盖不足",
    body_coverage_unverifiable:               "正文覆盖无法验证",
    gaps_detected:                            "检测到转写缺口",
    missing_sections:                         "缺少必要章节",
    missing_video_id:                         "缺少视频 ID",
    unexpected_video_id:                      "意外的视频 ID",
    qwen_overcompressed_body:                 "Qwen 正文过度压缩",
    qwen_fact_retention_low:                  "Qwen 关键事实保留率低",
    qwen_narrative_blocks_missing:            "Qwen 叙事证据块缺失",
    qwen_narrative_blocks_missing_from_final: "Qwen 最终稿叙事块缺失",
    qwen_narrative_body_ratio_low:            "Qwen 叙事正文比率低",
    qwen_timeline_overlaps:                   "Qwen 时间线章节重叠",
    qwen_missing_chapter_fields:              "Qwen 章节字段缺失",
    qwen_missing_prompt_keywords:             "Qwen 提示词关键词缺失",
    qwen_missing_required_sections:           "Qwen 必要章节缺失",
    qwen_missing_technical_asset_appendix:    "Qwen 技术资产附录缺失",
    qwen_missing_timestamped_chapters:        "Qwen 时间戳章节缺失",
    qwen_technical_asset_code_blocks_low:     "Qwen 技术资产代码块不足",
    qwen_window_unreferenced:                 "Qwen 窗口笔记未引用",
  };
  const label = keyZh[key] ?? key;
  if (!detail) return label;
  const d = detail
    .replace(/last chapter ([0-9:]+), gap (\d+s)/, "最后章节 $1，缺口 $2")
    .replace(/body\/transcript ratio ([\d.]+), expected >= ([\d.]+)/, "正文\/转写比 $1，期望 >= $2")
    .replace(/no ### \[HH:MM:SS - HH:MM:SS\] chapters found/, "未找到时间戳章节")
    .replace(/expected Prompts \/ Code \/ Config appendix/, "期望包含 Prompts/Code/Config 附录")
    .replace(/expected preserved prompt\/code\/config fences/, "期望保留提示词\/代码\/配置代码块");
  return `${label}：${d}`;
}

// ── DragDropZone ──────────────────────────────────────────────────────────────

function DragDropZone({
  onFile,
  lang,
}: {
  onFile: (name: string) => void;
  lang: Lang;
}) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file?.name.toLowerCase().endsWith(".mp4")) onFile(file.name);
  }

  return (
    <div
      className={`drop-zone ${dragging ? "dragging" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
    >
      <Upload size={20} />
      <span>{t(lang, "dropMp4")}</span>
      <small>{t(lang, "dropMp4Sub")}</small>
      <input
        ref={inputRef}
        type="file"
        accept=".mp4,video/mp4"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file.name);
          e.target.value = "";
        }}
      />
    </div>
  );
}

// ── SourceCard ────────────────────────────────────────────────────────────────

function SourceCard({
  type,
  active,
  lang,
  onClick,
}: {
  type: SourceType;
  active?: boolean;
  lang: Lang;
  onClick?: () => void;
}) {
  const Icon = SOURCE_ICONS[type];
  return (
    <button
      className={`source-card ${active ? "active" : ""}`}
      type="button"
      onClick={onClick}
    >
      <Icon size={18} />
      <span>{SOURCE_LABELS[type][lang]}</span>
    </button>
  );
}

// ── RunPlanPanel ──────────────────────────────────────────────────────────────

function RunPlanPanel({
  plan,
  lang,
  onSave,
  saving,
}: {
  plan: RunPlan;
  lang: Lang;
  onSave?: () => void;
  saving?: boolean;
}) {
  return (
    <section className="panel full plan-panel">
      <div className="panel-heading">
        <Terminal size={18} />
        <h2>{t(lang, "dryRunTitle")}</h2>
      </div>
      <div className="plan-summary">
        <div>
          <span>{t(lang, "planSource")}</span>
          <strong>{SOURCE_LABELS[plan.source_type as SourceType]?.[lang] ?? plan.source_type}</strong>
        </div>
        <div><span>{t(lang, "planBase")}</span><strong>{plan.base}</strong></div>
        <div><span>{t(lang, "planProvider")}</span><strong>{plan.provider}</strong></div>
        <div><span>{t(lang, "planPass")}</span><strong>{plan.synthesis_pass}</strong></div>
      </div>
      {!!plan.warnings.length && (
        <div className="warnings plan-warnings">
          {plan.warnings.map((w) => (
            <div className="warning" key={w}>
              <AlertTriangle size={16} />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}
      <div className="command-list">
        {plan.commands.map((cmd) => (
          <div className="command-item" key={`${cmd.stage}-${cmd.command}`}>
            <div className="command-head">
              <strong>{cmd.label}</strong>
              <span>{_STAGE_LABELS_ZH[cmd.stage]?.[lang] ?? cmd.stage}</span>
            </div>
            <code>{cmd.command}</code>
            <p>{cmd.summary}</p>
          </div>
        ))}
      </div>
      <div className="path-grid">
        {Object.entries(plan.paths).map(([key, value]) => (
          <div key={key}>
            <span>{_PATH_KEY_ZH[key]?.[lang] ?? key.replace(/_/g, " ").toLowerCase()}</span>
            <code>{value || t(lang, "notPlanned")}</code>
          </div>
        ))}
      </div>
      {onSave && (
        <button
          className="secondary-button save-plan-button"
          type="button"
          onClick={onSave}
          disabled={saving}
        >
          <CheckCircle2 size={16} />
          {saving ? t(lang, "btnSaving") : t(lang, "btnSaveRun")}
        </button>
      )}
    </section>
  );
}

// ── EmptyPanel ────────────────────────────────────────────────────────────────

function EmptyPanel({ title, text }: { title: string; text: string }) {
  return (
    <section className="panel full">
      <div className="panel-heading">
        <Activity size={18} />
        <h2>{title}</h2>
      </div>
      <p className="empty-text">{text}</p>
    </section>
  );
}

// ── RunList ───────────────────────────────────────────────────────────────────

function RunList({
  runs,
  selectedId,
  lang,
  onSelect,
}: {
  runs: RunRecord[];
  selectedId?: string;
  lang: Lang;
  onSelect: (run: RunRecord) => void;
}) {
  return (
    <div className="run-list">
      {runs.map((run) => {
        const Icon = SOURCE_ICONS[run.source_type];
        return (
          <button
            key={run.id}
            className={`run-row ${selectedId === run.id ? "selected" : ""}`}
            type="button"
            onClick={() => onSelect(run)}
          >
            <div className="run-row-top">
              <span className="run-source">
                <Icon size={15} /> {SOURCE_LABELS[run.source_type][lang]}
              </span>
              <span className={`status-pill ${run.status}`}>
                {statusLabel(run.status, lang)}
              </span>
            </div>
            <div className="run-name">{run.base}</div>
            <div className="run-metrics">
              <span>{run.metrics.chunks} {t(lang, "metricsChunks")}</span>
              <span>{run.metrics.frames} {t(lang, "metricsFrames")}</span>
              {run.metrics.warnings > 0 && (
                <span>{run.metrics.warnings} {t(lang, "metricsWarnings")}</span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ── Overview ──────────────────────────────────────────────────────────────────

function Overview({
  run,
  lang,
  onLaunch,
  launching,
}: {
  run: RunRecord;
  lang: Lang;
  onLaunch?: () => void;
  launching?: boolean;
}) {
  return (
    <div className="overview-grid">
      <section className="panel">
        <div className="panel-heading">
          <Activity size={18} />
          <h2>{t(lang, "pipelineTitle")}</h2>
          {run.status === "created" && onLaunch && (
            <button
              className="launch-button"
              type="button"
              onClick={onLaunch}
              disabled={launching}
            >
              <Play size={14} />
              {launching ? t(lang, "btnLaunchingRun") : t(lang, "btnLaunchRun")}
            </button>
          )}
        </div>
        <div className="timeline">
          {run.steps.map((step) => (
            <div key={step.key} className={`timeline-step ${step.status}`}>
              <div className="step-dot" />
              <div>
                <div className="step-title">{stepLabel(step.key, step.label, lang)}</div>
                <div className="step-summary">{stepSummary(step.summary, lang)}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <Gauge size={18} />
          <h2>{t(lang, "runHealthTitle")}</h2>
        </div>
        <div className="health-grid">
          <div><span>{t(lang, "healthSource")}</span><strong>{qcStatusValue(run.qc?.source_status ?? "unknown", lang)}</strong></div>
          <div><span>{t(lang, "healthCoverage")}</span><strong>{qcStatusValue(run.qc?.body_coverage_status ?? "pending", lang)}</strong></div>
          <div><span>{t(lang, "healthTailGap")}</span><strong>{
            (() => {
              const v = run.qc?.body_tail_gap_s;
              if (v == null) return "—";
              if (v < 0) return lang === "zh" ? "异常" : "invalid";
              return `${v}s`;
            })()
          }</strong></div>
          <div><span>{t(lang, "healthProvider")}</span><strong>{run.provider ?? "none"}</strong></div>
        </div>
        <div className="path-box">
          <span>{t(lang, "finalMarkdown")}</span>
          <code>{run.paths.markdown ?? t(lang, "notGenerated")}</code>
        </div>
      </section>
    </div>
  );
}

// ── Chunks ────────────────────────────────────────────────────────────────────

function Chunks({ run, lang }: { run: RunRecord; lang: Lang }) {
  const isLive = RUNNING_STATUSES.has(run.status) && run.chunks.length === 0;
  const [liveChunks, setLiveChunks] = useState<import("./types").ChunkRecord[]>([]);

  // Reset when not live
  useEffect(() => {
    if (!isLive) setLiveChunks([]);
  }, [isLive]);

  // Initial fetch immediately when live starts
  useEffect(() => {
    if (!isLive) return;
    fetchLiveChunks(run.id).then((r) => setLiveChunks(r.chunks)).catch(() => {});
  }, [run.id, isLive]);

  // Background-tab-safe polling every 5s
  useWorkerInterval(() => {
    fetchLiveChunks(run.id).then((r) => setLiveChunks(r.chunks)).catch(() => {});
  }, 5000, isLive);

  const displayChunks = isLive ? liveChunks : run.chunks;

  return (
    <section className="panel full">
      <div className="panel-heading">
        <Boxes size={18} />
        <h2>
          {t(lang, "metricsChunks")}
          {isLive && (
            <span className="live-badge">
              <span className="live-dot" />
              {t(lang, "liveRecording")} · {liveChunks.length} {t(lang, "metricsChunks")}
            </span>
          )}
          {!isLive && displayChunks.length > 0 && (
            <span className="count-badge">{displayChunks.length}</span>
          )}
        </h2>
      </div>
      {displayChunks.length === 0 ? (
        <p className="empty-text">
          {isLive ? t(lang, "waitFirstChunk") : t(lang, "noChunkData")}
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t(lang, "thIndex")}</th>
                <th>{t(lang, "thStart")}</th>
                <th>{t(lang, "thDuration")}</th>
                <th>{t(lang, "thChars")}</th>
                <th>{t(lang, "thSegments")}</th>
                <th>{t(lang, "thFrames")}</th>
                <th>{t(lang, "thBackend")}</th>
              </tr>
            </thead>
            <tbody>
              {displayChunks.map((chunk) => (
                <tr key={`${chunk.index}-${chunk.start_s}`}>
                  <td>{chunk.index}</td>
                  <td>{formatSeconds(chunk.start_s)}</td>
                  <td>{formatSeconds(chunk.duration_s)}</td>
                  <td>{chunk.transcript_chars.toLocaleString()}</td>
                  <td>{chunk.segments}</td>
                  <td>{chunk.frames}</td>
                  <td>{chunk.backend}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── QcPanel ───────────────────────────────────────────────────────────────────

function QcPanel({ run, lang }: { run: RunRecord; lang: Lang }) {
  const qc = run.qc;
  return (
    <section className="panel full">
      <div className="panel-heading">
        <Gauge size={18} />
        <h2>QC</h2>
      </div>
      <div className="qc-grid">
        <div><span>{t(lang, "qcSourceStatus")}</span><strong>{qcStatusValue(qc?.source_status ?? "unknown", lang)}</strong></div>
        <div><span>{t(lang, "qcBodyCoverage")}</span><strong>{qcStatusValue(qc?.body_coverage_status ?? "pending", lang)}</strong></div>
        <div><span>{t(lang, "qcFrames")}</span><strong>{qc?.frame_count ?? run.metrics.frames}</strong></div>
        <div><span>{t(lang, "qcWindows")}</span><strong>{qc?.qwen_window_policy?.window_count ?? "-"}</strong></div>
        <div><span>{t(lang, "qcCoveredFrames")}</span><strong>{qc?.qwen_window_policy?.covered_new_frames ?? "-"}</strong></div>
        <div><span>{t(lang, "qcOverlap")}</span><strong>{qc?.qwen_window_policy?.overlap_frames ?? "-"}</strong></div>
      </div>
      <div className="warnings">
        {(qc?.warnings ?? []).map((w) => (
          <div className="warning" key={w}>
            <AlertTriangle size={16} />
            <span>{localizeWarning(w, lang)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Keyframes ─────────────────────────────────────────────────────────────────

function frameUrl(path: string): string {
  if (!path) return "";
  return `/api/frames?p=${encodeURIComponent(path)}`;
}

function Keyframes({ run, lang }: { run: RunRecord; lang: Lang }) {
  if (!run.frames.length) {
    return (
      <EmptyPanel
        title={TAB_LABELS.Keyframes[lang]}
        text={t(lang, "noKeyframes")}
      />
    );
  }
  return (
    <section className="panel full">
      <div className="panel-heading">
        <ImageIcon size={18} />
        <h2>
          {TAB_LABELS.Keyframes[lang]}
          <span className="count-badge">{run.frames.length}</span>
        </h2>
      </div>
      <div className="frame-grid">
        {run.frames.map((frame) => (
          <div className="frame-tile" key={`${frame.timestamp_s}-${frame.type}`}>
            {frame.path ? (
              <img
                className={`frame-img ${frame.type}`}
                src={frameUrl(frame.path)}
                alt={`${frame.type} @ ${formatSeconds(frame.timestamp_s)}`}
                loading="lazy"
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.display = "none";
                }}
              />
            ) : (
              <div className={`frame-thumb ${frame.type}`}>
                <ImageIcon size={24} />
              </div>
            )}
            <div className="frame-meta">
              <strong>{formatSeconds(frame.timestamp_s)}</strong>
              <span>{frame.type} · chunk {frame.chunk_index ?? "-"}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── TextPanel ─────────────────────────────────────────────────────────────────

function TextPanel({
  title,
  icon,
  lang,
  text,
}: {
  title: string;
  icon: "transcript" | "markdown";
  lang: Lang;
  text?: string;
}) {
  const Icon = icon === "transcript" ? FileText : CheckCircle2;
  return (
    <section className="panel full">
      <div className="panel-heading">
        <Icon size={18} />
        <h2>{title}</h2>
      </div>
      <pre className="text-preview">{text || t(lang, "waitingApiData")}</pre>
    </section>
  );
}

// ── LogsPanel ─────────────────────────────────────────────────────────────────

function LogsPanel({ run, lang }: { run: RunRecord; lang: Lang }) {
  const logs = run.logs ?? [];
  if (!logs.length) {
    return <EmptyPanel title={TAB_LABELS.Logs[lang]} text={t(lang, "noLogs")} />;
  }
  return (
    <section className="panel full">
      <div className="panel-heading">
        <Terminal size={18} />
        <h2>{TAB_LABELS.Logs[lang]}</h2>
      </div>
      <div className="log-list">
        {logs.map((entry, index) => (
          <div className={`log-row ${entry.level}`} key={`${entry.time}-${index}`}>
            <span>{entry.time}</span>
            <strong>{entry.level}</strong>
            <p>{entry.message}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── DetailTab ─────────────────────────────────────────────────────────────────

function DetailTab({
  tab,
  run,
  lang,
  onLaunch,
  launching,
}: {
  tab: Tab;
  run: RunRecord;
  lang: Lang;
  onLaunch?: () => void;
  launching?: boolean;
}) {
  if (tab === "Overview") return <Overview run={run} lang={lang} onLaunch={onLaunch} launching={launching} />;
  if (tab === "Plan") {
    return run.plan
      ? <RunPlanPanel plan={run.plan} lang={lang} />
      : <EmptyPanel title={TAB_LABELS.Plan[lang]} text={t(lang, "planEmptyText")} />;
  }
  if (tab === "Logs") return <LogsPanel run={run} lang={lang} />;
  if (tab === "Chunks") return <Chunks run={run} lang={lang} />;
  if (tab === "QC") return <QcPanel run={run} lang={lang} />;
  if (tab === "Keyframes") return <Keyframes run={run} lang={lang} />;
  if (tab === "Transcript") {
    return (
      <TextPanel
        title={TAB_LABELS.Transcript[lang]}
        icon="transcript"
        lang={lang}
        text={run.transcript_preview}
      />
    );
  }
  return <TextPanel title="Markdown" icon="markdown" lang={lang} text={run.markdown_preview} />;
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [lang, setLang] = useState<Lang>("zh");
  const [config, setConfig] = useState<ServerConfig>({ launch_mode: "simulate", readonly: false, running_statuses: [] });
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(false);
  const [detectedPlatform, setDetectedPlatform] = useState<"zhihu" | "xiaoe" | "unknown">("zhihu");
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [selectedRun, setSelectedRun] = useState<RunRecord>();
  const [activeTab, setActiveTab] = useState<Tab>("Overview");
  const [loadingIndex, setLoadingIndex] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sourceType, setSourceType] = useState<SourceType>("live");
  const [source, setSource] = useState("");
  const [base, setBase] = useState("");
  const [provider, setProvider] = useState<RunPlanRequest["provider"]>("gemini");
  const [synthesisPass, setSynthesisPass] = useState<RunPlanRequest["synthesis_pass"]>("one-shot");
  const [qwenMaxFrames, setQwenMaxFrames] = useState(250);
  const [query, setQuery] = useState("");
  const [runPlan, setRunPlan] = useState<RunPlan>();
  const [planError, setPlanError] = useState("");
  const [planning, setPlanning] = useState(false);
  const [savingRun, setSavingRun] = useState(false);
  const [launching, setLaunching] = useState(false);
  // pollRef removed — replaced by useWorkerInterval (background-tab safe)

  useEffect(() => {
    fetchConfig().then(setConfig);
    setLoadingIndex(true);
    fetchRuns()
      .then((items) => {
        setRuns(items);
        setSelectedId(items[0]?.id);
      })
      .finally(() => setLoadingIndex(false));
  }, []);

  useEffect(() => {
    if (!selectedId) { setSelectedRun(undefined); return; }
    setLoadingDetail(true);
    fetchRun(selectedId)
      .then((run) => setSelectedRun(run))
      .finally(() => setLoadingDetail(false));
  }, [selectedId]);

  // Poll selected run every 3s while it is in a running state.
  // useWorkerInterval keeps ticking even when the tab is hidden (background-tab safe).
  const isRunPolling = !!(selectedId && selectedRun && RUNNING_STATUSES.has(selectedRun.status));
  useWorkerInterval(() => {
    if (!selectedId) return;
    fetchRun(selectedId).then((run) => {
      setSelectedRun(run);
      setRuns((items) => items.map((item) => (item.id === run.id ? run : item)));
      if (!RUNNING_STATUSES.has(run.status) && run.status === "completed") {
        setTimeout(() => refreshIndex(), 2000);
      }
    }).catch(() => {});
  }, 3000, isRunPolling);

  function handleLaunch() {
    if (!selectedId) return;
    setLaunching(true);
    launchRun(selectedId)
      .then((run) => {
        setSelectedRun(run);
        setRuns((items) => items.map((item) => (item.id === run.id ? run : item)));
      })
      .catch((err) => console.error("Launch failed:", err))
      .finally(() => setLaunching(false));
  }

  function refreshIndex() {
    setLoadingIndex(true);
    fetchRuns().then((items) => {
      setRuns(items);
      const existing = items.find((run) => run.id === selectedId);
      setSelectedId(existing?.id ?? items[0]?.id);
    }).finally(() => setLoadingIndex(false));
  }

  const sourcePlaceholder: Record<SourceType, string> = {
    mp4:    "Videos/example.mp4",
    replay: "https://www.zhihu.com/xen/training/live/room/...?type=replay",
    live:   "https://www.zhihu.com/xen/training/live/room/...",
  };

  function checkAuth() {
    setCheckingAuth(true);
    fetchAuthStatus()
      .then(setAuthStatus)
      .finally(() => setCheckingAuth(false));
  }

  function selectSourceType(type: SourceType) {
    setSourceType(type);
    setSource("");
    if (type === "replay") {
      setProvider("qwen");
      setSynthesisPass("sliding-window");
    } else {
      setProvider("gemini");
      setSynthesisPass("one-shot");
    }
    if (type === "live") {
      setDetectedPlatform("zhihu");
      checkAuth();
    } else {
      setAuthStatus(null);
      setDetectedPlatform("unknown");
    }
  }

  // Detect platform from URL in real-time
  function detectPlatformFromUrl(url: string): "zhihu" | "xiaoe" | "unknown" {
    if (!url) return "unknown";
    const lowered = url.toLowerCase();
    if (lowered.includes("xiaoeknow.com") || lowered.includes("xet.pomoho.com") || lowered.includes("xiaoecloud.com")) {
      return "xiaoe";
    }
    if (lowered.includes("zhihu.com") || lowered.includes("csslcloud.net")) {
      return "zhihu";
    }
    return "unknown";
  }

  // Check auth for the detected platform
  function checkAuthForPlatform(platform: string, url?: string) {
    setCheckingAuth(true);
    fetchAuthStatus(platform, url)
      .then(setAuthStatus)
      .finally(() => setCheckingAuth(false));
  }

  function checkAuth() {
    checkAuthForPlatform(detectedPlatform, source);
  }

  function currentPlanRequest(): RunPlanRequest {
    return {
      source_type: sourceType,
      source,
      base,
      provider,
      synthesis_pass: synthesisPass,
      qwen_max_frames: qwenMaxFrames,
    };
  }

  function submitPlan() {
    setPlanning(true);
    setPlanError("");
    createRunPlan(currentPlanRequest())
      .then((plan) => setRunPlan(plan))
      .catch((err) => setPlanError(err instanceof Error ? err.message : "Failed to create dry run"))
      .finally(() => setPlanning(false));
  }

  function saveCreatedRun() {
    setSavingRun(true);
    setPlanError("");
    createRun(currentPlanRequest())
      .then((run) => {
        setRunPlan(undefined);
        setSelectedId(run.id);
        setSelectedRun(run);
        setActiveTab("Plan");
        setRuns((items) => [run, ...items.filter((item) => item.id !== run.id)]);
      })
      .catch((err) => setPlanError(err instanceof Error ? err.message : "Failed to save run"))
      .finally(() => setSavingRun(false));
  }

  async function directLaunch() {
    if (!source.trim()) {
      setPlanError(t(lang, "errNoSource"));
      return;
    }
    setLaunching(true);
    setPlanError("");
    try {
      const run = await createRun(currentPlanRequest());
      setRuns((items) => [run, ...items.filter((i) => i.id !== run.id)]);
      setSelectedId(run.id);
      setSelectedRun(run);
      setRunPlan(undefined);
      setActiveTab("Overview");
      const launched = await launchRun(run.id);
      setSelectedRun(launched);
      setRuns((items) => items.map((i) => (i.id === launched.id ? launched : i)));
    } catch (err) {
      let msg = err instanceof Error ? err.message : "";
      if (msg.includes("403")) {
        msg = lang === "zh"
          ? "服务器为只读模式，请用 start_mac_live.sh 重启 API"
          : "Server is read-only — restart with start_mac_live.sh";
      } else if (msg.includes("409") || msg.includes("正在运行") || msg.includes("active run")) {
        msg = lang === "zh"
          ? "该源已有正在运行的任务，请等待完成后再启动"
          : "A task for this source is already running — wait for it to finish";
      }
      setPlanError(msg || t(lang, "errLaunchFail"));
    } finally {
      setLaunching(false);
    }
  }

  const sourceInputLabel: Record<SourceType, string> = {
    mp4:    t(lang, "labelMp4"),
    replay: t(lang, "labelReplay"),
    live:   t(lang, "labelLive"),
  };

  return (
    <main className="app-shell">
      <aside className="sidebar">

        {/* Brand + language toggle */}
        <div className="brand">
          <div className="brand-mark"><CirclePlay size={21} /></div>
          <div className="brand-text">
            <h1>{t(lang, "brandTitle")}</h1>
            <p>{t(lang, "brandSub")}</p>
          </div>
          <div className="lang-toggle">
            <button
              className={lang === "zh" ? "active" : ""}
              type="button"
              onClick={() => setLang("zh")}
            >
              中
            </button>
            <button
              className={lang === "en" ? "active" : ""}
              type="button"
              onClick={() => setLang("en")}
            >
              EN
            </button>
          </div>
        </div>

        {/* Create panel */}
        <section className="create-panel">
          <div className="section-title">{t(lang, "createSource")}</div>

          <div className="source-grid">
            <SourceCard type="mp4"    active={sourceType === "mp4"}    lang={lang} onClick={() => selectSourceType("mp4")} />
            <SourceCard type="replay" active={sourceType === "replay"} lang={lang} onClick={() => selectSourceType("replay")} />
            <SourceCard type="live"   active={sourceType === "live"}   lang={lang} onClick={() => selectSourceType("live")} />
          </div>

          {/* Auth status badge — only shown for live stream */}
          {sourceType === "live" && (
            <div className={`auth-badge ${authStatus ? (authStatus.ok ? "ok" : "fail") : "idle"}`}>
              {detectedPlatform === "xiaoe" && (
                <span className="platform-tag">小鹅通</span>
              )}
              {checkingAuth ? (
                <span>{lang === "zh" ? "检查登录状态…" : "Checking auth…"}</span>
              ) : authStatus ? (
                <>
                  <span className="auth-dot" />
                  <span>{authStatus.message}</span>
                  <button type="button" className="auth-recheck" onClick={checkAuth}>
                    {lang === "zh" ? "重检" : "Recheck"}
                  </button>
                </>
              ) : (
                <button type="button" className="auth-recheck" onClick={checkAuth}>
                  {lang === "zh" ? "检查登录状态" : "Check auth"}
                </button>
              )}
            </div>
          )}

          <label className="input-label">
            {sourceInputLabel[sourceType]}
            {sourceType === "mp4" ? (
              <>
                <DragDropZone
                  lang={lang}
                  onFile={(name) => setSource(`Videos/${name}`)}
                />
                <div className="input-row">
                  <Search size={16} />
                  <input
                    value={source}
                    placeholder={sourcePlaceholder.mp4}
                    onChange={(e) => setSource(e.target.value)}
                  />
                </div>
              </>
            ) : (
              <>
                <div
                  className="input-row"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    const url =
                      e.dataTransfer.getData("text/uri-list") ||
                      e.dataTransfer.getData("text/plain");
                    if (url?.trim()) setSource(url.trim());
                  }}
                >
                  <Search size={16} />
                  <input
                    value={source}
                    placeholder={sourcePlaceholder[sourceType]}
                    onChange={(e) => {
                      const url = e.target.value;
                      setSource(url);
                      if (sourceType === "live") {
                        const plat = detectPlatformFromUrl(url);
                        setDetectedPlatform(plat);
                        if (plat !== "unknown") checkAuthForPlatform(plat, url);
                      }
                    }}
                  />
                </div>
                <p className="drop-hint">{t(lang, "dropUrlHint")}</p>
              </>
            )}
          </label>

          <label className="input-label">
            {t(lang, "outputBase")}
            <input
              className="plain-input"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder={t(lang, "outputBasePh")}
            />
          </label>

          <div className="form-grid">
            <label className="input-label compact">
              {t(lang, "providerLabel")}
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value as RunPlanRequest["provider"])}
              >
                <option value="gemini">Gemini</option>
                <option value="qwen">Qwen</option>
              </select>
            </label>
            <label className="input-label compact">
              {t(lang, "passLabel")}
              <select
                value={synthesisPass}
                onChange={(e) =>
                  setSynthesisPass(e.target.value as RunPlanRequest["synthesis_pass"])
                }
              >
                <option value="one-shot">one-shot</option>
                <option value="sliding-window">sliding-window</option>
              </select>
            </label>
          </div>

          <label className="input-label">
            {t(lang, "qwenMaxFrames")}
            <input
              className="plain-input"
              type="number"
              min={1}
              max={250}
              value={qwenMaxFrames}
              onChange={(e) => setQwenMaxFrames(Number(e.target.value))}
            />
          </label>

          {config.launch_mode === "simulate" && (
            <div className="mode-banner simulate">
              <AlertTriangle size={13} />
              <span>{lang === "zh" ? "模拟模式 — 不执行真实任务。WIN 用 start_win.bat，Mac 用 start_mac_live.sh 启动真实模式" : "Simulate mode — no real pipeline runs. Use start_win.bat (WIN) or start_mac_live.sh (Mac) for live mode."}</span>
            </div>
          )}

          {planError && (
            <div className="inline-error">
              <AlertTriangle size={15} />
              <span>{planError}</span>
            </div>
          )}

          {/* Primary action: direct launch */}
          <button
            className="primary-button"
            type="button"
            onClick={directLaunch}
            disabled={launching || planning}
          >
            <Play size={16} />
            {launching ? t(lang, "btnLaunching") : t(lang, "btnLaunch")}
          </button>

          {/* Secondary: dry-run preview */}
          <button
            className="secondary-button dry-run-button"
            type="button"
            onClick={submitPlan}
            disabled={planning || launching}
          >
            <Upload size={16} />
            {planning ? t(lang, "btnPlanning") : t(lang, "btnDryRun")}
          </button>
        </section>

        {/* Runs list */}
        <section className="runs-panel">
          <div className="section-title">
            {t(lang, "runsTitle")}
            {loadingIndex && (
              <span style={{ fontWeight: 400, textTransform: "none", color: "#66727a" }}>
                {t(lang, "runsLoading")}
              </span>
            )}
          </div>
          <div className="search-row">
            <Search size={13} />
            <input
              className="search-input"
              placeholder={t(lang, "filterPh")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <RunList
            runs={
              query
                ? runs.filter((r) =>
                    r.base.toLowerCase().includes(query.toLowerCase())
                  )
                : runs
            }
            selectedId={selectedId}
            lang={lang}
            onSelect={(run) => setSelectedId(run.id)}
          />
        </section>
      </aside>

      {/* Workspace */}
      <section className="workspace">
        <header className="workspace-header">
          <div>
            <div className="eyebrow">
              {selectedRun
                ? SOURCE_LABELS[selectedRun.source_type][lang]
                : lang === "zh" ? "任务" : "Run"}
            </div>
            <h2>{selectedRun?.base ?? t(lang, "noRunSelected")}</h2>
            <p>
              {selectedRun?.model ?? t(lang, "waitingData")} ·{" "}
              {selectedRun?.synthesis_pass ?? "one-shot"}
            </p>
          </div>
          <button
            className="secondary-button"
            type="button"
            onClick={refreshIndex}
            disabled={loadingIndex}
          >
            <RefreshCw size={16} />
            {loadingIndex ? t(lang, "btnRefreshing") : t(lang, "btnRefresh")}
          </button>
        </header>

        {runPlan && (
          <RunPlanPanel
            plan={runPlan}
            lang={lang}
            onSave={saveCreatedRun}
            saving={savingRun}
          />
        )}

        {!selectedRun && !runPlan && (
          <div className="empty-workspace">
            <div className="empty-workspace-icon">
              <CirclePlay size={26} />
            </div>
            <h3>{loadingDetail ? t(lang, "loadingRun") : t(lang, "noRunSelected")}</h3>
            {!loadingDetail && (
              <p>{lang === "zh" ? "从左侧选择一个已有任务，或填写参数后点击「启动」开始新任务" : "Select a run on the left, or fill in the form and click Launch to start a new one."}</p>
            )}
          </div>
        )}

        {selectedRun && (
          <>
            <div className="metrics-strip">
              <div>
                <span>{t(lang, "metricsChunks")}</span>
                <strong>{selectedRun.metrics.chunks}</strong>
              </div>
              <div>
                <span>{t(lang, "metricsTranscript")}</span>
                <strong>{selectedRun.metrics.transcript_chars.toLocaleString()}</strong>
              </div>
              <div>
                <span>{t(lang, "metricsFrames")}</span>
                <strong>{selectedRun.metrics.frames}</strong>
              </div>
              <div>
                <span>{t(lang, "metricsWarnings")}</span>
                <strong>{selectedRun.metrics.warnings}</strong>
              </div>
            </div>

            <nav className="tabs">
              {tabs.map((tab) => (
                <button
                  key={tab}
                  className={activeTab === tab ? "active" : ""}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                >
                  {TAB_LABELS[tab][lang]}
                </button>
              ))}
            </nav>

            {loadingDetail && (
              <div className="detail-loading">{t(lang, "loadingDetail")}</div>
            )}

            <DetailTab
              tab={activeTab}
              run={selectedRun}
              lang={lang}
              onLaunch={handleLaunch}
              launching={launching}
            />
          </>
        )}
      </section>
    </main>
  );
}

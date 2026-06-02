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
  Video
} from "lucide-react";
import { RUNNING_STATUSES, createRun, createRunPlan, fetchLiveChunks, fetchRun, fetchRuns, launchRun } from "./api";
import type { RunPlan, RunPlanRequest, RunRecord, SourceType } from "./types";

const sourceMeta: Record<SourceType, { label: string; icon: typeof Film }> = {
  mp4: { label: "MP4", icon: Film },
  replay: { label: "Replay", icon: Video },
  live: { label: "Live", icon: Radio }
};

const tabs = ["Overview", "Plan", "Logs", "Chunks", "QC", "Keyframes", "Transcript", "Markdown"] as const;
type Tab = (typeof tabs)[number];

function formatSeconds(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return [h, m, s].map((part) => String(part).padStart(2, "0")).join(":");
}

function statusLabel(status: string): string {
  return status.replace("_", " ");
}

function SourceCard({ type, active, onClick }: { type: SourceType; active?: boolean; onClick?: () => void }) {
  const meta = sourceMeta[type];
  const Icon = meta.icon;
  return (
    <button className={`source-card ${active ? "active" : ""}`} type="button" onClick={onClick}>
      <Icon size={18} />
      <span>{meta.label}</span>
    </button>
  );
}

function RunPlanPanel({ plan, onSave, saving }: { plan: RunPlan; onSave?: () => void; saving?: boolean }) {
  return (
    <section className="panel full plan-panel">
      <div className="panel-heading">
        <Terminal size={18} />
        <h2>Dry Run Plan</h2>
      </div>
      <div className="plan-summary">
        <div><span>Source</span><strong>{sourceMeta[plan.source_type].label}</strong></div>
        <div><span>Base</span><strong>{plan.base}</strong></div>
        <div><span>Provider</span><strong>{plan.provider}</strong></div>
        <div><span>Pass</span><strong>{plan.synthesis_pass}</strong></div>
      </div>
      {!!plan.warnings.length && (
        <div className="warnings plan-warnings">
          {plan.warnings.map((warning) => (
            <div className="warning" key={warning}>
              <AlertTriangle size={16} />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}
      <div className="command-list">
        {plan.commands.map((command) => (
          <div className="command-item" key={`${command.stage}-${command.command}`}>
            <div className="command-head">
              <strong>{command.label}</strong>
              <span>{command.stage}</span>
            </div>
            <code>{command.command}</code>
            <p>{command.summary}</p>
          </div>
        ))}
      </div>
      <div className="path-grid">
        {Object.entries(plan.paths).map(([key, value]) => (
          <div key={key}>
            <span>{key}</span>
            <code>{value || "not planned"}</code>
          </div>
        ))}
      </div>
      {onSave && (
        <button className="secondary-button save-plan-button" type="button" onClick={onSave} disabled={saving}>
          <CheckCircle2 size={16} />
          {saving ? "Saving" : "Save created run"}
        </button>
      )}
    </section>
  );
}

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

function RunList({ runs, selectedId, onSelect }: { runs: RunRecord[]; selectedId?: string; onSelect: (run: RunRecord) => void }) {
  return (
    <div className="run-list">
      {runs.map((run) => {
        const SourceIcon = sourceMeta[run.source_type].icon;
        return (
          <button key={run.id} className={`run-row ${selectedId === run.id ? "selected" : ""}`} type="button" onClick={() => onSelect(run)}>
            <div className="run-row-top">
              <span className="run-source"><SourceIcon size={15} /> {sourceMeta[run.source_type].label}</span>
              <span className={`status-pill ${run.status}`}>{statusLabel(run.status)}</span>
            </div>
            <div className="run-name">{run.base}</div>
            <div className="run-metrics">
              <span>{run.metrics.chunks} chunks</span>
              <span>{run.metrics.frames} frames</span>
              <span>{run.metrics.warnings} warnings</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function Overview({ run, onLaunch, launching }: { run: RunRecord; onLaunch?: () => void; launching?: boolean }) {
  return (
    <div className="overview-grid">
      <section className="panel">
        <div className="panel-heading">
          <Activity size={18} />
          <h2>Pipeline</h2>
          {run.status === "created" && onLaunch && (
            <button className="launch-button" type="button" onClick={onLaunch} disabled={launching}>
              <Play size={14} />
              {launching ? "Starting…" : "Launch"}
            </button>
          )}
        </div>
        <div className="timeline">
          {run.steps.map((step) => (
            <div key={step.key} className={`timeline-step ${step.status}`}>
              <div className="step-dot" />
              <div>
                <div className="step-title">{step.label}</div>
                <div className="step-summary">{step.summary}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <Gauge size={18} />
          <h2>Run Health</h2>
        </div>
        <div className="health-grid">
          <div><span>Source</span><strong>{run.qc?.source_status ?? "unknown"}</strong></div>
          <div><span>Coverage</span><strong>{run.qc?.body_coverage_status ?? "pending"}</strong></div>
          <div><span>Tail Gap</span><strong>{run.qc?.body_tail_gap_s ?? 0}s</strong></div>
          <div><span>Provider</span><strong>{run.provider ?? "none"}</strong></div>
        </div>
        <div className="path-box">
          <span>Final Markdown</span>
          <code>{run.paths.markdown ?? "not generated"}</code>
        </div>
      </section>
    </div>
  );
}

function Chunks({ run }: { run: RunRecord }) {
  const isLive = RUNNING_STATUSES.has(run.status) && run.chunks.length === 0;
  const [liveChunks, setLiveChunks] = useState<import("./types").ChunkRecord[]>([]);

  useEffect(() => {
    if (!isLive) { setLiveChunks([]); return; }
    let active = true;
    const poll = () => {
      fetchLiveChunks(run.id)
        .then((r) => { if (active) setLiveChunks(r.chunks); })
        .catch(() => {/* silently ignore poll errors */});
    };
    poll();
    const timer = setInterval(poll, 5000);
    return () => { active = false; clearInterval(timer); };
  }, [run.id, isLive]);

  const displayChunks = isLive ? liveChunks : run.chunks;

  return (
    <section className="panel full">
      <div className="panel-heading">
        <Boxes size={18} />
        <h2>
          Chunks
          {isLive && (
            <span className="live-badge">
              <span className="live-dot" />
              Recording · {liveChunks.length} chunks
            </span>
          )}
          {!isLive && displayChunks.length > 0 && (
            <span className="count-badge">{displayChunks.length}</span>
          )}
        </h2>
      </div>
      {displayChunks.length === 0 ? (
        <EmptyPanel
          title=""
          text={isLive ? "Waiting for first chunk… (polling every 5s)" : "No chunk data available."}
        />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Start</th>
                <th>Duration</th>
                <th>Chars</th>
                <th>Segments</th>
                <th>Frames</th>
                <th>Backend</th>
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

function QcPanel({ run }: { run: RunRecord }) {
  const qc = run.qc;
  return (
    <section className="panel full">
      <div className="panel-heading">
        <Gauge size={18} />
        <h2>QC</h2>
      </div>
      <div className="qc-grid">
        <div><span>source_status</span><strong>{qc?.source_status ?? "unknown"}</strong></div>
        <div><span>body_coverage</span><strong>{qc?.body_coverage_status ?? "pending"}</strong></div>
        <div><span>frames</span><strong>{qc?.frame_count ?? run.metrics.frames}</strong></div>
        <div><span>windows</span><strong>{qc?.qwen_window_policy?.window_count ?? "-"}</strong></div>
        <div><span>covered frames</span><strong>{qc?.qwen_window_policy?.covered_new_frames ?? "-"}</strong></div>
        <div><span>overlap</span><strong>{qc?.qwen_window_policy?.overlap_frames ?? "-"}</strong></div>
      </div>
      <div className="warnings">
        {(qc?.warnings ?? []).map((warning) => (
          <div className="warning" key={warning}>
            <AlertTriangle size={16} />
            <span>{warning}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function frameUrl(path: string): string {
  if (!path) return "";
  return `/api/frames?p=${encodeURIComponent(path)}`;
}

function Keyframes({ run }: { run: RunRecord }) {
  if (!run.frames.length) {
    return <EmptyPanel title="Keyframes" text="No keyframe data available for this run." />;
  }
  return (
    <section className="panel full">
      <div className="panel-heading">
        <ImageIcon size={18} />
        <h2>Keyframes <span className="count-badge">{run.frames.length}</span></h2>
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
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
              />
            ) : (
              <div className={`frame-thumb ${frame.type}`}><ImageIcon size={24} /></div>
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

function TextPanel({ title, icon, text }: { title: string; icon: "transcript" | "markdown"; text?: string }) {
  const Icon = icon === "transcript" ? FileText : CheckCircle2;
  return (
    <section className="panel full">
      <div className="panel-heading">
        <Icon size={18} />
        <h2>{title}</h2>
      </div>
      <pre className="text-preview">{text || "Waiting for API data."}</pre>
    </section>
  );
}

function LogsPanel({ run }: { run: RunRecord }) {
  const logs = run.logs ?? [];
  if (!logs.length) return <EmptyPanel title="Logs" text="No web run logs have been recorded for this artifact-backed run." />;
  return (
    <section className="panel full">
      <div className="panel-heading">
        <Terminal size={18} />
        <h2>Logs</h2>
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

function DetailTab({ tab, run, onLaunch, launching }: { tab: Tab; run: RunRecord; onLaunch?: () => void; launching?: boolean }) {
  if (tab === "Overview") return <Overview run={run} onLaunch={onLaunch} launching={launching} />;
  if (tab === "Plan") return run.plan ? <RunPlanPanel plan={run.plan} /> : <EmptyPanel title="Plan" text="This run was discovered from final QC artifacts, so no web-created plan is attached." />;
  if (tab === "Logs") return <LogsPanel run={run} />;
  if (tab === "Chunks") return <Chunks run={run} />;
  if (tab === "QC") return <QcPanel run={run} />;
  if (tab === "Keyframes") return <Keyframes run={run} />;
  if (tab === "Transcript") return <TextPanel title="Transcript" icon="transcript" text={run.transcript_preview} />;
  return <TextPanel title="Markdown" icon="markdown" text={run.markdown_preview} />;
}

export default function App() {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [selectedRun, setSelectedRun] = useState<RunRecord>();
  const [activeTab, setActiveTab] = useState<Tab>("Overview");
  const [loadingIndex, setLoadingIndex] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sourceType, setSourceType] = useState<SourceType>("live");
  const [source, setSource] = useState("https://www.zhihu.com/xen/training/live/room/...");
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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setLoadingIndex(true);
    fetchRuns().then((items) => {
      setRuns(items);
      const nextId = items[0]?.id;
      setSelectedId(nextId);
    }).finally(() => setLoadingIndex(false));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelectedRun(undefined);
      return;
    }
    setLoadingDetail(true);
    fetchRun(selectedId)
      .then((run) => setSelectedRun(run))
      .finally(() => setLoadingDetail(false));
  }, [selectedId]);

  // Poll selected run every 3s while it is in a running state.
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (!selectedId || !selectedRun || !RUNNING_STATUSES.has(selectedRun.status)) return;
    pollRef.current = setInterval(() => {
      fetchRun(selectedId).then((run) => {
        setSelectedRun(run);
        setRuns((items) => items.map((item) => (item.id === run.id ? run : item)));
        if (!RUNNING_STATUSES.has(run.status)) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          // Pipeline finished: refresh the full run list so the new QC artifact
          // replaces the web: registry entry with real chunk/frame/qc data.
          if (run.status === "completed") {
            setTimeout(() => refreshIndex(), 2000);
          }
        }
      }).catch(() => {/* ignore transient poll errors */});
    }, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [selectedId, selectedRun?.status]);

  function handleLaunch() {
    if (!selectedId) return;
    setLaunching(true);
    launchRun(selectedId)
      .then((run) => {
        setSelectedRun(run);
        setRuns((items) => items.map((item) => (item.id === run.id ? run : item)));
      })
      .catch((error) => console.error("Launch failed:", error))
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
    mp4:    "D:\\zhihu\\Videos\\example.mp4  (本机绝对路径)",
    replay: "https://www.zhihu.com/xen/training/live/room/...?type=replay",
    live:   "https://www.zhihu.com/xen/training/live/room/...",
  };
  const sourceLabel: Record<SourceType, string> = {
    mp4:    "本地 MP4 文件路径",
    replay: "回放视频 URL",
    live:   "直播间 URL",
  };

  function selectSourceType(type: SourceType) {
    setSourceType(type);
    if (type === "mp4") {
      setSource("");
      setProvider("gemini");
      setSynthesisPass("one-shot");
    } else if (type === "replay") {
      setSource("");
      setProvider("qwen");
      setSynthesisPass("sliding-window");
    } else {
      setSource("");
      setProvider("gemini");
      setSynthesisPass("one-shot");
    }
  }

  function currentPlanRequest(): RunPlanRequest {
    return {
      source_type: sourceType,
      source,
      base,
      provider,
      synthesis_pass: synthesisPass,
      qwen_max_frames: qwenMaxFrames
    };
  }

  function submitPlan() {
    setPlanning(true);
    setPlanError("");
    createRunPlan(currentPlanRequest())
      .then((plan) => setRunPlan(plan))
      .catch((error) => setPlanError(error instanceof Error ? error.message : "Failed to create dry run"))
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
      .catch((error) => setPlanError(error instanceof Error ? error.message : "Failed to save run"))
      .finally(() => setSavingRun(false));
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><CirclePlay size={21} /></div>
          <div>
            <h1>zhihu Workbench</h1>
            <p>Pipeline visualization</p>
          </div>
        </div>

        <section className="create-panel">
          <div className="section-title">Create Source</div>
          <div className="source-grid">
            <SourceCard type="mp4" active={sourceType === "mp4"} onClick={() => selectSourceType("mp4")} />
            <SourceCard type="replay" active={sourceType === "replay"} onClick={() => selectSourceType("replay")} />
            <SourceCard type="live" active={sourceType === "live"} onClick={() => selectSourceType("live")} />
          </div>
          <label className="input-label">
            {sourceLabel[sourceType]}
            <div className="input-row">
              <Search size={16} />
              <input
                value={source}
                placeholder={sourcePlaceholder[sourceType]}
                onChange={(event) => setSource(event.target.value)}
              />
            </div>
          </label>
          <label className="input-label">
            Output base
            <input className="plain-input" value={base} onChange={(event) => setBase(event.target.value)} placeholder="Auto if empty" />
          </label>
          <div className="form-grid">
            <label className="input-label compact">
              Provider
              <select value={provider} onChange={(event) => setProvider(event.target.value as RunPlanRequest["provider"])}>
                <option value="gemini">Gemini</option>
                <option value="qwen">Qwen</option>
              </select>
            </label>
            <label className="input-label compact">
              Pass
              <select value={synthesisPass} onChange={(event) => setSynthesisPass(event.target.value as RunPlanRequest["synthesis_pass"])}>
                <option value="one-shot">one-shot</option>
                <option value="sliding-window">sliding-window</option>
              </select>
            </label>
          </div>
          <label className="input-label">
            Qwen max frames
            <input className="plain-input" type="number" min={1} max={250} value={qwenMaxFrames} onChange={(event) => setQwenMaxFrames(Number(event.target.value))} />
          </label>
          {planError && (
            <div className="inline-error">
              <AlertTriangle size={15} />
              <span>{planError}</span>
            </div>
          )}
          <button className="primary-button" type="button" onClick={submitPlan} disabled={planning}>
            <Upload size={16} />
            {planning ? "Planning" : "Create dry run"}
          </button>
        </section>

        <section className="runs-panel">
          <div className="section-title">Runs {loadingIndex ? "· loading" : ""}</div>
          <div className="search-row">
            <Search size={13} />
            <input
              className="search-input"
              placeholder="Filter by name…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <RunList
            runs={query ? runs.filter((r) => r.base.toLowerCase().includes(query.toLowerCase())) : runs}
            selectedId={selectedId}
            onSelect={(run) => setSelectedId(run.id)}
          />
        </section>
      </aside>

      <section className="workspace">
        <header className="workspace-header">
          <div>
            <div className="eyebrow">{selectedRun ? sourceMeta[selectedRun.source_type].label : "Run"}</div>
            <h2>{selectedRun?.base ?? "No run selected"}</h2>
            <p>{selectedRun?.model ?? "Waiting for run data"} · {selectedRun?.synthesis_pass ?? "one-shot"}</p>
          </div>
          <button className="secondary-button" type="button" onClick={refreshIndex} disabled={loadingIndex}>
            <RefreshCw size={16} />
            {loadingIndex ? "Refreshing" : "Refresh index"}
          </button>
        </header>

        {runPlan && <RunPlanPanel plan={runPlan} onSave={saveCreatedRun} saving={savingRun} />}

        {!selectedRun && !runPlan && (
          <section className="panel full">
            <div className="panel-heading">
              <Activity size={18} />
              <h2>{loadingDetail ? "Loading run" : "No run selected"}</h2>
            </div>
          </section>
        )}

        {selectedRun && (
          <>

            <div className="metrics-strip">
              <div><span>Chunks</span><strong>{selectedRun.metrics.chunks}</strong></div>
              <div><span>Transcript</span><strong>{selectedRun.metrics.transcript_chars.toLocaleString()}</strong></div>
              <div><span>Frames</span><strong>{selectedRun.metrics.frames}</strong></div>
              <div><span>Warnings</span><strong>{selectedRun.metrics.warnings}</strong></div>
            </div>

            <nav className="tabs">
              {tabs.map((tab) => (
                <button key={tab} className={activeTab === tab ? "active" : ""} type="button" onClick={() => setActiveTab(tab)}>
                  {tab}
                </button>
              ))}
            </nav>

            {loadingDetail && <div className="detail-loading">Loading detail from API...</div>}
            <DetailTab tab={activeTab} run={selectedRun} onLaunch={handleLaunch} launching={launching} />
          </>
        )}
      </section>
    </main>
  );
}

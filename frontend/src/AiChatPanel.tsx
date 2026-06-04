import { useEffect, useRef, useState } from "react";
import { Bot, ChevronUp, CheckCircle2, Loader2, Send, Terminal, XCircle } from "lucide-react";
import type { Lang } from "./i18n";
import { t } from "./i18n";
import { createRun, launchRun, sendAiChat } from "./api";
import type { ChatMessage, ToolCallResult } from "./types";
import type { RunPlanRequest } from "./types";

// ── Props ─────────────────────────────────────────────────────────────────────

interface AiChatPanelProps {
  lang: Lang;
  open: boolean;
  onToggle: () => void;
  onRunSelected?: (runId: string) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function genId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function RunsTable({
  runs,
  onRunSelected,
}: {
  runs: Array<Record<string, unknown>>;
  onRunSelected?: (id: string) => void;
}) {
  return (
    <div className="ai-tool-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Base</th>
            <th>Status</th>
            <th>Type</th>
            <th>Provider</th>
          </tr>
        </thead>
        <tbody>
          {runs.slice(0, 10).map((run) => (
            <tr
              key={String(run.id)}
              className={onRunSelected ? "ai-clickable-row" : ""}
              onClick={() => onRunSelected?.(String(run.id))}
            >
              <td>{String(run.base ?? run.id)}</td>
              <td>
                <span className={`status-pill ${run.status}`}>{String(run.status)}</span>
              </td>
              <td>{String(run.source_type)}</td>
              <td>{String(run.provider ?? "-")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunDetail({ run }: { run: Record<string, unknown> }) {
  const steps = run.steps as Array<Record<string, unknown>> | undefined;
  return (
    <div>
      <dl className="ai-dl">
        <dt>Base</dt><dd>{String(run.base)}</dd>
        <dt>Status</dt><dd><span className={`status-pill ${run.status}`}>{String(run.status)}</span></dd>
        <dt>Provider</dt><dd>{String(run.provider ?? "-")}</dd>
        <dt>Model</dt><dd>{String(run.model ?? "-")}</dd>
      </dl>
      {steps && steps.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {steps.map((s) => (
            <div key={String(s.key)} style={{ fontSize: 11, marginBottom: 2 }}>
              <span className={`status-pill ${s.status}`} style={{ fontSize: 10 }}>{String(s.status)}</span>
              {" "}{String(s.key)} — {String(s.summary)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PlanCard({ plan }: { plan: Record<string, unknown> }) {
  const warnings = (plan.warnings as string[]) ?? [];
  const commands = (plan.commands as Array<Record<string, unknown>>) ?? [];
  return (
    <div>
      <div className="ai-plan-meta">
        <span>来源: {String(plan.source_type)}</span>
        <span>Base: {String(plan.base)}</span>
        <span>Provider: {String(plan.provider)}</span>
        <span>Pass: {String(plan.synthesis_pass)}</span>
      </div>
      {warnings.length > 0 && (
        <div className="ai-plan-warnings">
          {warnings.map((w, i) => (
            <div key={i} className="ai-warn-item">⚠ {w}</div>
          ))}
        </div>
      )}
      <div className="ai-plan-commands">
        {commands.slice(0, 3).map((cmd, i) => (
          <div key={i} className="ai-cmd-item">
            <strong>{String(cmd.label)}</strong>
            <code>{String(cmd.command)}</code>
          </div>
        ))}
        {commands.length > 3 && (
          <div className="ai-cmd-more">+ {commands.length - 3} 条命令</div>
        )}
      </div>
    </div>
  );
}

function AuthCard({ result }: { result: Record<string, unknown> }) {
  const ok = Boolean(result.ok);
  return (
    <div className={`ai-auth-card ${ok ? "ok" : "fail"}`}>
      <span className="ai-auth-dot" />
      <span>{String(result.message ?? (ok ? "已登录" : "未登录"))}</span>
    </div>
  );
}

function LaunchProposal({ args }: { args: Record<string, unknown> }) {
  return (
    <dl className="ai-dl">
      <dt>类型</dt><dd>{String(args.source_type)}</dd>
      <dt>来源</dt><dd><code style={{ fontSize: 11 }}>{String(args.source)}</code></dd>
      <dt>Provider</dt><dd>{String(args.provider)}</dd>
      {args.synthesis_pass ? <><dt>模式</dt><dd>{String(args.synthesis_pass)}</dd></> : null}
    </dl>
  );
}

function ToolResultCard({
  tc,
  lang,
  msgId,
  onConfirm,
  onCancel,
  onRunSelected,
}: {
  tc: ToolCallResult;
  lang: Lang;
  msgId: string;
  onConfirm: (args: Record<string, unknown>, msgId: string) => void;
  onCancel: (msgId: string) => void;
  onRunSelected?: (id: string) => void;
}) {
  const result = tc.result as Record<string, unknown> | unknown;

  function renderBody() {
    if (tc.name === "list_runs" && Array.isArray(result)) {
      return (
        <RunsTable
          runs={result as Array<Record<string, unknown>>}
          onRunSelected={onRunSelected}
        />
      );
    }
    if (tc.name === "get_run" && result && typeof result === "object" && !Array.isArray(result)) {
      return <RunDetail run={result as Record<string, unknown>} />;
    }
    if (tc.name === "create_plan" && result && typeof result === "object" && !Array.isArray(result)) {
      return <PlanCard plan={result as Record<string, unknown>} />;
    }
    if (tc.name === "check_auth" && result && typeof result === "object" && !Array.isArray(result)) {
      return <AuthCard result={result as Record<string, unknown>} />;
    }
    if (tc.name === "launch_run") {
      if (tc.requires_confirmation) {
        return <LaunchProposal args={tc.args} />;
      }
      const r = result as Record<string, unknown>;
      return (
        <div style={{ color: "var(--primary)", fontSize: 12 }}>
          ✅ {String(r?.message ?? "已执行")}
        </div>
      );
    }
    const r = result as Record<string, unknown>;
    if (r?.error) {
      return (
        <div style={{ color: "var(--err-text)", fontSize: 12 }}>
          ❌ {String(r.error)}
        </div>
      );
    }
    return <pre className="ai-tool-raw">{JSON.stringify(result, null, 2)}</pre>;
  }

  return (
    <div className="ai-tool-card">
      <div className="ai-tool-card-header">
        <Terminal size={10} />
        {tc.name}
      </div>
      <div className="ai-tool-card-body">{renderBody()}</div>
      {tc.requires_confirmation && tc.name === "launch_run" && (
        <div className="ai-confirm-bar">
          <span>{t(lang, "aiChatConfirmHint")}</span>
          <button
            className="ai-confirm-yes"
            type="button"
            onClick={() => onConfirm(tc.args, msgId)}
          >
            <CheckCircle2 size={12} />
            {t(lang, "aiChatConfirm")}
          </button>
          <button
            className="ai-confirm-no"
            type="button"
            onClick={() => onCancel(msgId)}
          >
            <XCircle size={12} />
            {t(lang, "aiChatCancel")}
          </button>
        </div>
      )}
    </div>
  );
}

function ChatBubble({
  msg,
  lang,
  onConfirm,
  onCancel,
  onRunSelected,
}: {
  msg: ChatMessage;
  lang: Lang;
  onConfirm: (args: Record<string, unknown>, msgId: string) => void;
  onCancel: (msgId: string) => void;
  onRunSelected?: (id: string) => void;
}) {
  return (
    <div className={`ai-bubble ${msg.role}`}>
      {msg.content && <div className="ai-bubble-content">{msg.content}</div>}
      {msg.tool_calls?.map((tc, i) => (
        <ToolResultCard
          key={i}
          tc={tc}
          lang={lang}
          msgId={msg.id}
          onConfirm={onConfirm}
          onCancel={onCancel}
          onRunSelected={onRunSelected}
        />
      ))}
      <span className="ai-bubble-time">
        {new Date(msg.timestamp).toLocaleTimeString()}
      </span>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function AiChatPanel({ lang, open, onToggle, onRunSelected }: AiChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  async function handleSend(text: string) {
    if (!text.trim() || loading) return;

    const userMsg: ChatMessage = {
      id: genId(),
      role: "user",
      content: text.trim(),
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText("");
    setLoading(true);
    setError("");

    const apiMessages = [...messages, userMsg]
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }));

    try {
      const result = await sendAiChat(apiMessages);

      if (result.error) {
        setError(result.error);
        return;
      }

      const assistantMsg: ChatMessage = {
        id: genId(),
        role: "assistant",
        content: result.reply,
        tool_calls: result.tool_calls?.length ? result.tool_calls : undefined,
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t(lang, "aiChatError"));
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm(proposedArgs: Record<string, unknown>, msgId: string) {
    const req: RunPlanRequest = {
      source_type: (proposedArgs.source_type as RunPlanRequest["source_type"]) || "live",
      source: String(proposedArgs.source ?? ""),
      base: String(proposedArgs.base ?? ""),
      provider: (proposedArgs.provider as RunPlanRequest["provider"]) || "gemini",
      synthesis_pass:
        (proposedArgs.synthesis_pass as RunPlanRequest["synthesis_pass"]) || "one-shot",
      qwen_max_frames: Number(proposedArgs.qwen_max_frames ?? 250),
    };

    setLoading(true);
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? {
              ...m,
              tool_calls: m.tool_calls?.map((tc) =>
                tc.requires_confirmation ? { ...tc, requires_confirmation: false } : tc
              ),
            }
          : m
      )
    );

    try {
      const run = await createRun(req);
      await launchRun(run.id);
      setMessages((prev) => [
        ...prev,
        {
          id: genId(),
          role: "assistant",
          content: `✅ 任务已启动 — ID: ${run.id}`,
          timestamp: Date.now(),
        },
      ]);
      onRunSelected?.(run.id);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: genId(),
          role: "assistant",
          content: `❌ 启动失败：${err instanceof Error ? err.message : "未知错误"}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleCancel(msgId: string) {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? {
              ...m,
              tool_calls: m.tool_calls?.map((tc) =>
                tc.requires_confirmation ? { ...tc, requires_confirmation: false } : tc
              ),
            }
          : m
      )
    );
  }

  return (
    <div className="ai-chat-panel">
      <button className="ai-chat-toggle" onClick={onToggle} type="button">
        <Bot size={14} />
        <span>{t(lang, "aiChatToggle")}</span>
        <span className="ai-toggle-spacer" />
        <ChevronUp size={13} className={open ? "rotated" : ""} />
      </button>

      {open && (
        <div className="ai-chat-body">
          <div className="ai-chat-messages" ref={scrollRef}>
            {messages.length === 0 && !loading && (
              <p className="ai-chat-empty">{t(lang, "aiChatEmpty")}</p>
            )}
            {messages.map((msg) => (
              <ChatBubble
                key={msg.id}
                msg={msg}
                lang={lang}
                onConfirm={handleConfirm}
                onCancel={handleCancel}
                onRunSelected={onRunSelected}
              />
            ))}
            {loading && (
              <div className="ai-chat-loading">
                <Loader2 size={13} className="ai-spin" />
                {t(lang, "aiChatLoading")}
              </div>
            )}
          </div>

          <div className="ai-chat-input-row">
            <input
              className="ai-chat-input"
              placeholder={t(lang, "aiChatPlaceholder")}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && inputText.trim()) {
                  e.preventDefault();
                  handleSend(inputText);
                }
              }}
              disabled={loading}
            />
            <button
              className="ai-chat-send-btn"
              onClick={() => handleSend(inputText)}
              disabled={loading || !inputText.trim()}
              type="button"
            >
              <Send size={14} />
            </button>
          </div>

          {error && <p className="ai-chat-error">{error}</p>}
        </div>
      )}
    </div>
  );
}

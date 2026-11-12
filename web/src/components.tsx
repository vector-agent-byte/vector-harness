import { useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { ChatMessage, LiveTurn, StatusKind, TodoItem } from "./types.ts"

export function Markdown({ text }: { text: string }) {
  if (text === "") return null
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  )
}

export function TodoList({ todos }: { todos: TodoItem[] }) {
  const done = todos.filter((t) => t.status === "completed").length
  const pct = todos.length > 0 ? Math.round((done / todos.length) * 100) : 0
  return (
    <div className="plan-card">
      <div className="plan-header">
        <span className="plan-label">计划</span>
        <span className="plan-fraction">{done} / {todos.length}</span>
        <div className="plan-bar-wrap">
          <div className="plan-bar-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <ul className="plan-list">
        {todos.map((todo, i) => (
          <li key={todo.id ?? i} className={`plan-item ${todo.status}`}>
            <span className="plan-icon" aria-hidden="true">
              {todo.status === "completed" ? "✓" : todo.status === "in_progress" ? "▶" : "○"}
            </span>
            <span className="plan-content">{todo.content}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ReflectionCard({ pass, text }: { pass: boolean; text: string }) {
  return (
    <div className={`reflection-card ${pass ? "pass" : "fail"}`}>
      <span className="reflection-verdict">{pass ? "反思通过" : "反思未通过"}</span>
      {text ? <span className="reflection-text">{text}</span> : null}
    </div>
  )
}

export function parseReflection(content: string): { pass: boolean; text: string } | null {
  const m = content.match(/^\[Reflection\]\s*(通过|未通过)\s*[—-]\s*(.*)$/s)
  if (!m) return null
  return { pass: m[1] === "通过", text: m[2].trim() }
}

export function ThinkingBlock({ text, streaming }: { text: string; streaming: boolean }) {
  const [expanded, setExpanded] = useState(true)
  const prevStreaming = useRef(streaming)
  useEffect(() => {
    if (prevStreaming.current && !streaming) setExpanded(false)
    prevStreaming.current = streaming
  }, [streaming])
  return (
    <div className="thinking-block">
      <button
        type="button"
        className="thinking-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="thinking-sparkle" aria-hidden="true">✦</span>
        <span className="thinking-title">思考</span>
        {streaming ? <span className="thinking-pulse" aria-hidden="true" /> : null}
        <span className="thinking-chevron" aria-hidden="true">{expanded ? "▴" : "▾"}</span>
      </button>
      {expanded ? (
        <div className="thinking-body">
          <Markdown text={text} />
        </div>
      ) : null}
    </div>
  )
}

const STATUS_CONFIG: Record<string, { icon: string; title: string; hint: string; kind: StatusKind }> = {
  max_steps: { icon: "⚡", title: "已达步数上限", hint: "任务可能未完整执行，可继续输入指令", kind: "warn" },
  error:     { icon: "✕", title: "模型请求失败", hint: "接口出错，请稍后重试或检查配置", kind: "error" },
  stopped:   { icon: "◼", title: "已停止", hint: "任务已手动中止", kind: "neutral" },
}

export function StatusNote({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? { icon: "·", title: status, hint: "", kind: "neutral" as StatusKind }
  return (
    <div className={`status-note status-note-${cfg.kind}`}>
      <span className="status-note-icon" aria-hidden="true">{cfg.icon}</span>
      <div className="status-note-body">
        <span className="status-note-title">{cfg.title}</span>
        {cfg.hint ? <span className="status-note-hint">{cfg.hint}</span> : null}
      </div>
    </div>
  )
}

function traceRoleLabel(role: string): string {
  if (role === "user") return "用户"
  if (role === "assistant") return "助手"
  if (role === "tool") return "工具"
  return role
}

function traceSnippet(msg: ChatMessage): string {
  if (msg.tool_calls && msg.tool_calls.length > 0) {
    return msg.tool_calls
      .filter((c) => c.name)
      .map((c) => {
        const arg = c.args ? Object.entries(c.args).map(([k, v]) => `${k}=${String(v).slice(0, 40)}`).join(", ") : ""
        return `${c.name}(${arg})`
      })
      .join(" · ")
  }
  return msg.content.replace(/\s+/g, " ").slice(0, 160)
}

export function TraceView({ messages, live }: { messages: ChatMessage[]; live: LiveTurn | null }) {
  const rows: Array<{ role: string; label: string; snippet: string; isError: boolean; isLive: boolean }> = []
  for (const msg of messages) {
    if (!msg.content && !msg.tool_calls?.length) continue
    rows.push({
      role: msg.role,
      label: traceRoleLabel(msg.role),
      snippet: traceSnippet(msg),
      isError: msg.is_error,
      isLive: false,
    })
  }
  if (live) {
    if (live.thinking) rows.push({ role: "thinking", label: "思考", snippet: live.thinking.replace(/\s+/g, " ").slice(0, 160), isError: false, isLive: true })
    if (live.text) rows.push({ role: "assistant", label: "助手", snippet: live.text.replace(/\s+/g, " ").slice(0, 160), isError: false, isLive: true })
    for (const tool of live.tools) {
      if (tool.name) rows.push({ role: "tool", label: "工具", snippet: tool.name, isError: false, isLive: true })
    }
  }
  return (
    <div className="trace-view">
      {rows.map((row, i) => (
        <div key={i} className={`trace-row trace-${row.role}${row.isError ? " is-error" : ""}${row.isLive ? " is-live" : ""}`}>
          <span className="trace-role">{row.label}</span>
          <span className="trace-snippet">{row.snippet}</span>
        </div>
      ))}
      {rows.length === 0 ? <div className="trace-empty">暂无轨迹</div> : null}
    </div>
  )
}

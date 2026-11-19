import { useCallback, useEffect, useRef, useState } from "react"
import type { FormEvent, KeyboardEvent } from "react"
import { normalizeMessages, readError, readEventStream } from "./api.ts"
import { Markdown } from "./components.tsx"
import {
  extractResearchTasks,
  extractResearchTasksFromDelegates,
  extractResearchTopic,
  extractTaskDetail,
  getResearchProgress,
  splitTaskContent,
} from "./deepResearch.ts"
import type { ResearchTask, ResearchTaskDetail, ResearchTaskStatus } from "./deepResearch.ts"
import type { ChatMessage, StreamEvent } from "./types.ts"

type ResearchSessionStatus = "idle" | "running" | "complete" | "error"

type ResearchSession = {
  id: string
  topic: string
  messages: ChatMessage[]
  status: ResearchSessionStatus
  updated_at: number
  eventCount: number
}

const RESEARCH_SESSION_KEY = "vh-research-open"

function buildResearchPrompt(topic: string, engine: string): string {
  return `请对以下主题进行深度研究：

主题：${topic}

搜索引擎偏好：${engine === "advanced" ? "高级搜索，优先学术和权威来源" : "标准搜索"}

请将研究分解为5个子任务，每个子任务聚焦一个具体研究方向。
对每个子任务，请：
1. 通过搜索获取最新信息
2. 整理关键发现和数据来源
3. 形成该方向的简要总结，以笔记形式保存

完成所有子任务后，汇总形成完整研究报告。`
}

export default function DeepResearch() {
  const [sessions, setSessions] = useState<ResearchSession[]>([])
  const [openId, setOpenId] = useState<string | null>(null)
  const [topicDraft, setTopicDraft] = useState("")
  const [engine, setEngine] = useState<"advanced" | "standard">("advanced")
  const [running, setRunning] = useState(false)
  const [selectedTaskIndex, setSelectedTaskIndex] = useState<number | null>(null)
  const [flowCollapsed, setFlowCollapsed] = useState(false)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [liveTasks, setLiveTasks] = useState<ResearchTask[]>([])
  const [logOpen, setLogOpen] = useState(false)

  const openIdRef = useRef<string | null>(null)
  const runningRef = useRef(false)

  const openSession = sessions.find((s) => s.id === openId) ?? null
  // Prefer update_todos tasks (plan mode), fall back to delegate children (subagents mode)
  const todoTasks = openSession ? extractResearchTasks(openSession.messages) : []
  const delegateTasks = openSession ? extractResearchTasksFromDelegates(openSession.messages) : []
  const baseTasks = todoTasks.length > 0 ? todoTasks : delegateTasks
  const tasks = running && liveTasks.length > 0 ? liveTasks : baseTasks
  const progress = getResearchProgress(tasks)
  const isRunning = openSession?.status === "running"

  const taskDetail: ResearchTaskDetail | null =
    selectedTaskIndex !== null && openSession
      ? extractTaskDetail(selectedTaskIndex, openSession.messages)
      : null

  const selectedTask: ResearchTask | null =
    selectedTaskIndex !== null ? (tasks[selectedTaskIndex] ?? null) : null

  const totalEvents = openSession?.eventCount ?? 0

  const loadSession = useCallback(async (id: string): Promise<ChatMessage[] | null> => {
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { cache: "no-store" })
      if (!res.ok) return null
      const body = (await res.json()) as Record<string, unknown>
      return normalizeMessages(body.messages)
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    const saved = sessionStorage.getItem(RESEARCH_SESSION_KEY)
    if (!saved) return
    void (async () => {
      const msgs = await loadSession(saved)
      if (!msgs) return
      const topic = extractResearchTopic(msgs)
      setSessions([{ id: saved, topic, messages: msgs, status: "complete", updated_at: Date.now(), eventCount: msgs.length }])
      setOpenId(saved)
      openIdRef.current = saved
    })()
  }, [loadSession])

  useEffect(() => {
    if (openId) sessionStorage.setItem(RESEARCH_SESSION_KEY, openId)
  }, [openId])

  async function startResearch() {
    if (running || !topicDraft.trim()) return
    setRunning(true)
    runningRef.current = true
    setErrorText(null)

    try {
      const createRes = await fetch("/api/sessions", { method: "POST" })
      if (!createRes.ok) {
        setErrorText("创建会话失败")
        return
      }
      const { id } = (await createRes.json()) as { id: string }

      await fetch(`/api/sessions/${encodeURIComponent(id)}/mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "subagents" }),
      })

      const newSession: ResearchSession = {
        id,
        topic: topicDraft.trim(),
        messages: [],
        status: "running",
        updated_at: Date.now(),
        eventCount: 0,
      }
      setSessions((prev) => [newSession, ...prev])
      setOpenId(id)
      openIdRef.current = id
      setSelectedTaskIndex(null)

      const msgRes = await fetch(`/api/sessions/${encodeURIComponent(id)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: buildResearchPrompt(topicDraft.trim(), engine) }),
      })

      if (!msgRes.ok) {
        const code = await readError(msgRes)
        setErrorText(code)
        setSessions((prev) => prev.map((s) => s.id === id ? { ...s, status: "error" } : s))
        return
      }

      // Poll session messages every 2 s while streaming so tasks appear in real-time
      const pollTimer = setInterval(async () => {
        if (!runningRef.current) return
        const msgs = await loadSession(id)
        if (msgs) {
          setSessions((prev) => prev.map((s) => s.id === id ? { ...s, messages: msgs } : s))
        }
      }, 2000)

      await readEventStream(msgRes, (event: StreamEvent) => {
        setSessions((prev) =>
          prev.map((s) => s.id === id ? { ...s, eventCount: s.eventCount + 1 } : s)
        )
        const isChild = event.origin === "child"
        if (
          !isChild &&
          event.kind === "tool_call_end" &&
          event.name === "update_todos" &&
          event.arguments &&
          typeof event.arguments === "object" &&
          Array.isArray((event.arguments as Record<string, unknown>).todos)
        ) {
          // plan mode: update_todos keeps the full list
          const rawTodos = (event.arguments as { todos: Array<{ id?: string; content: string; status: string }> }).todos
          setLiveTasks(rawTodos.map((todo, i) => {
            const { title, description } = splitTaskContent(todo.content)
            return { id: todo.id ?? `task-${i}`, index: i, title, description, status: todo.status as ResearchTaskStatus }
          }))
        } else if (
          !isChild &&
          event.kind === "tool_call_end" &&
          event.name === "delegate" &&
          event.arguments &&
          typeof event.arguments === "object"
        ) {
          // subagents mode: each delegate call = one task (initially queued)
          const args = event.arguments as Record<string, unknown>
          const taskText = typeof args.task === "string" ? args.task : ""
          const tid = typeof event.tool_call_id === "string" && event.tool_call_id ? event.tool_call_id : `d-${Date.now()}`
          if (taskText) {
            const { title, description } = splitTaskContent(taskText)
            setLiveTasks((prev) => {
              if (prev.find((t) => t.id === tid)) return prev
              return [...prev, { id: tid, index: prev.length, title, description, status: "pending" }]
            })
          }
        } else if (
          !isChild &&
          event.kind === "tool_execution_start" &&
          event.name === "delegate"
        ) {
          // delegate execution has begun → mark as in_progress
          const tid = typeof event.tool_call_id === "string" && event.tool_call_id ? event.tool_call_id : ""
          if (tid) {
            setLiveTasks((prev) => prev.map((t) => t.id === tid ? { ...t, status: "in_progress" as ResearchTaskStatus } : t))
          }
        } else if (!isChild && event.kind === "tool_result") {
          // delegate result received → mark as completed (or error)
          const tid = typeof event.tool_call_id === "string" && event.tool_call_id ? event.tool_call_id : ""
          const isErr = event.name === "error"
          if (tid) {
            setLiveTasks((prev) =>
              prev.map((t) =>
                t.id === tid ? { ...t, status: (isErr ? "error" : "completed") as ResearchTaskStatus } : t
              )
            )
          }
        }
      })

      clearInterval(pollTimer)
      setLiveTasks([])

      const msgs = await loadSession(id)
      if (msgs) {
        setSessions((prev) =>
          prev.map((s) =>
            s.id === id
              ? { ...s, messages: msgs, status: "complete", eventCount: msgs.length }
              : s
          )
        )
      } else {
        setSessions((prev) => prev.map((s) => s.id === id ? { ...s, status: "complete" } : s))
      }
    } catch (e) {
      setErrorText(String(e))
      setSessions((prev) =>
        prev.map((s) => s.id === openIdRef.current ? { ...s, status: "error" } : s)
      )
    } finally {
      setRunning(false)
      runningRef.current = false
    }
  }

  function onTopicKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      void startResearch()
    }
  }

  function onFormSubmit(e: FormEvent) {
    e.preventDefault()
    void startResearch()
  }

  function copyPath(path: string) {
    void navigator.clipboard.writeText(path).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const statusLabel = isRunning
    ? "● 研究进行中"
    : openSession?.status === "complete"
      ? "● 研究流程完成"
      : openSession?.status === "error"
        ? "● 研究出错"
        : "○ 等待开始"

  const statusClass = isRunning
    ? "research-status-running"
    : openSession?.status === "complete"
      ? "research-status-done"
      : openSession?.status === "error"
        ? "research-status-error"
        : "research-status-idle"

  return (
    <div className="research-app">
      {/* Left sidebar */}
      <aside className="research-left">
        <div className="research-left-header">
          <div className="research-title">
            <span className="research-title-icon">🔍</span>
            深度研究助手
          </div>
        </div>

        <form className="research-form" onSubmit={onFormSubmit}>
          <label className="research-field-label">研究主题</label>
          <textarea
            className="research-topic-input"
            placeholder="输入您想深入研究的主题…"
            value={topicDraft}
            disabled={running}
            onChange={(e) => setTopicDraft(e.target.value)}
            onKeyDown={onTopicKeyDown}
            rows={4}
          />

          <label className="research-field-label">搜索引擎</label>
          <select
            className="research-engine-select"
            value={engine}
            disabled={running}
            onChange={(e) => setEngine(e.target.value as "advanced" | "standard")}
          >
            <option value="advanced">advanced</option>
            <option value="standard">standard</option>
          </select>

          {openSession && (
            <>
              <label className="research-field-label">研究进度</label>
              <div className="research-progress-wrap">
                <div
                  className="research-progress-bar"
                  style={{ width: progress.total > 0 ? `${(progress.done / progress.total) * 100}%` : "0%" }}
                />
              </div>
              <div className="research-progress-label">
                {progress.done} / {progress.total} 任务完成
              </div>
            </>
          )}

          <button
            type="submit"
            className="research-start-btn"
            disabled={running || !topicDraft.trim()}
          >
            {running ? "研究中…" : "+ 开始新研究"}
          </button>
        </form>

        {errorText && (
          <div className="research-error">{errorText}</div>
        )}

        {openSession && tasks.length > 0 && (
          <div className="research-task-sidebar">
            <div className="research-task-sidebar-label">任务列表</div>
            <ul className="research-task-sidebar-list">
              {tasks.map((task, i) => (
                <li
                  key={task.id}
                  className={`research-task-sidebar-item ${task.status} ${selectedTaskIndex === i ? "is-selected" : ""}`}
                  onClick={() => setSelectedTaskIndex(i)}
                >
                  <span className="research-task-sidebar-title">{task.title || `任务 ${i + 1}`}</span>
                  <span className={`research-task-badge ${task.status}`}>
                    {task.status === "completed" ? "已完成" :
                     task.status === "skipped" ? "已跳过" :
                     task.status === "in_progress" ? "进行中" :
                     task.status === "error" ? "出错" : "待执行"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>

      {/* Main content */}
      <div className="research-main">
        {/* Top status bar */}
        {openSession && (
          <div className="research-topbar">
            <span className={`research-status-label ${statusClass}`}>{statusLabel}</span>
            <span className="research-topbar-sep" />
            <span className="research-topbar-info">任务进度：{progress.done} / {progress.total}</span>
            <span className="research-topbar-sep" />
            <button
              type="button"
              className={logOpen ? "research-log-btn is-active" : "research-log-btn"}
              onClick={() => setLogOpen((v) => !v)}
            >
              阶段记录 {totalEvents} 条
            </button>
            <div className="research-topbar-right">
              <button
                type="button"
                className="research-collapse-btn"
                onClick={() => setFlowCollapsed((v) => !v)}
              >
                {flowCollapsed ? "展开流程" : "收起流程"}
              </button>
            </div>
          </div>
        )}

        {!openSession ? (
          <div className="research-empty">
            <div className="research-empty-icon">🔍</div>
            <div className="research-empty-title">开始深度研究</div>
            <div className="research-empty-hint">在左侧输入研究主题，然后点击"开始新研究"</div>
          </div>
        ) : (
          <div className="research-content">
            {/* Center: task cards */}
            <div className="research-center">
              <div className="research-center-label">任务清单</div>
              {!flowCollapsed && tasks.length === 0 && (
                <div className="research-no-tasks">
                  {isRunning ? "正在规划研究任务…" : "暂无任务数据"}
                </div>
              )}
              {!flowCollapsed && (
                <div className="research-task-cards">
                  {tasks.map((task, i) => (
                    <div
                      key={task.id}
                      className={`research-task-card ${task.status} ${selectedTaskIndex === i ? "is-selected" : ""}`}
                      onClick={() => setSelectedTaskIndex(selectedTaskIndex === i ? null : i)}
                    >
                      <div className="research-task-card-header">
                        <span className="research-task-card-title">{task.title || `任务 ${i + 1}`}</span>
                        <span className={`research-task-badge ${task.status}`}>
                          {task.status === "completed" ? "已完成" :
                           task.status === "skipped" ? "已跳过" :
                           task.status === "in_progress" ? "进行中" :
                           task.status === "error" ? "出错" : "待执行"}
                        </span>
                      </div>
                      {task.description && (
                        <div className="research-task-card-desc">{task.description}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Right: task detail */}
            <div className="research-right">
              {selectedTask && taskDetail ? (
                <>
                  <div className="research-detail-title">{selectedTask.title}</div>
                  {selectedTask.description && (
                    <div className="research-detail-desc">{selectedTask.description}</div>
                  )}

                  {taskDetail.queries.length > 0 && (
                    <div className="research-detail-section">
                      <div className="research-detail-section-label">查询</div>
                      <div className="research-detail-queries">
                        {taskDetail.queries.map((q, i) => (
                          <span key={i} className="research-query-tag">{q.length > 120 ? q.slice(0, 120) + "…" : q}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {taskDetail.notePath && (
                    <div className="research-detail-section">
                      <div className="research-detail-section-label">笔记</div>
                      <div className="research-note-row">
                        <span className="research-note-name">
                          {taskDetail.notePath.split(/[/\\]/).pop()}
                        </span>
                        <span className="research-note-tag">笔记</span>
                      </div>
                      <div className="research-path-row">
                        <span className="research-path-label">路径：</span>
                        <span className="research-path-value">{taskDetail.notePath}</span>
                        <button
                          type="button"
                          className="research-copy-btn"
                          onClick={() => copyPath(taskDetail.notePath!)}
                        >
                          {copied ? "已复制" : "复制"}
                        </button>
                      </div>
                    </div>
                  )}

                  {taskDetail.sources.length > 0 && (
                    <div className="research-detail-section">
                      <div className="research-detail-section-label">最新来源</div>
                      <ul className="research-sources-list">
                        {taskDetail.sources.map((src, i) => (
                          <li key={i}>
                            <a
                              className="research-source-link"
                              href={src.url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {src.title} ↗
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {taskDetail.summary && (
                    <div className="research-detail-section research-summary-section">
                      <div className="research-detail-section-label">任务总结</div>
                      <div className="research-summary-body">
                        <Markdown text={taskDetail.summary} />
                      </div>
                    </div>
                  )}

                  {taskDetail.queries.length === 0 && taskDetail.sources.length === 0 && !taskDetail.summary && (
                    <div className="research-detail-empty">
                      {isRunning ? "任务正在执行中…" : "该任务尚无详细数据"}
                    </div>
                  )}
                </>
              ) : (
                <div className="research-detail-placeholder">
                  <div className="research-detail-placeholder-icon">📋</div>
                  <div>点击左侧任务列表或任务卡片查看详情</div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Log drawer */}
      {logOpen && openSession && (
        <div className="research-log-drawer">
          <div className="research-log-header">
            <span className="research-log-title">阶段记录</span>
            <span className="research-log-count">{openSession.messages.length} 条</span>
            <button
              type="button"
              className="research-log-close"
              aria-label="关闭"
              onClick={() => setLogOpen(false)}
            >
              ✕
            </button>
          </div>
          <div className="research-log-body">
            {openSession.messages.length === 0 ? (
              <div className="research-log-empty">暂无记录</div>
            ) : (
              openSession.messages.map((msg, i) => (
                <ResearchLogEntry key={i} msg={msg} index={i} />
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ResearchLogEntry({ msg, index }: { msg: ChatMessage; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const roleLabel =
    msg.role === "user" ? "用户" :
    msg.role === "assistant" ? "助手" :
    msg.role === "tool" ? "工具" : msg.role

  const roleCls =
    msg.role === "user" ? "log-role-user" :
    msg.role === "assistant" ? "log-role-assistant" :
    msg.role === "tool" ? "log-role-tool" : "log-role-other"

  const hasToolCalls = (msg.tool_calls?.filter(c => c.name).length ?? 0) > 0
  const isLong = msg.content.length > 300
  const displayContent = isLong && !expanded ? msg.content.slice(0, 300) + "…" : msg.content

  return (
    <div className={`research-log-entry ${roleCls}${msg.is_error ? " is-error" : ""}`}>
      <div className="research-log-entry-header">
        <span className="research-log-role">{roleLabel}</span>
        {msg.is_error && <span className="research-log-err">失败</span>}
        {msg.tool_call_id && (
          <span className="research-log-tool-id" title={msg.tool_call_id}>
            #{msg.tool_call_id.slice(-6)}
          </span>
        )}
      </div>
      {msg.content && (
        <div className="research-log-content">
          <Markdown text={displayContent} />
          {isLong && (
            <button
              type="button"
              className="research-log-expand"
              onClick={() => setExpanded(v => !v)}
            >
              {expanded ? "收起" : "展开全部"}
            </button>
          )}
        </div>
      )}
      {hasToolCalls && (
        <ul className="research-log-tools">
          {msg.tool_calls?.filter(c => c.name).map((call, j) => (
            <li key={j} className="research-log-tool-item">
              <span className="research-log-tool-name">{call.name}</span>
              {call.args && (
                <span className="research-log-tool-arg">
                  {JSON.stringify(call.args).slice(0, 100)}
                  {JSON.stringify(call.args).length > 100 ? "…" : ""}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="research-log-index">#{index + 1}</div>
    </div>
  )
}

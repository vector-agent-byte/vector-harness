import { useCallback, useEffect, useRef, useState } from "react"
import type { FormEvent, KeyboardEvent } from "react"
import { normalizeMessages, readError, readEventStream } from "./api.ts"
import { Markdown } from "./components.tsx"
import { formatRelativeTime } from "./format.ts"
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

const RESEARCH_IDS_KEY = "vh-research-ids"
const RESEARCH_OPEN_KEY = "vh-research-open"
const RESEARCH_META_KEY = "vh-research-meta"

type ResearchMeta = { topic: string; updated_at: number }

function loadMeta(): Record<string, ResearchMeta> {
  try { return JSON.parse(localStorage.getItem(RESEARCH_META_KEY) ?? "{}") as Record<string, ResearchMeta> }
  catch { return {} }
}
function saveMeta(id: string, meta: ResearchMeta) {
  const all = loadMeta()
  all[id] = meta
  localStorage.setItem(RESEARCH_META_KEY, JSON.stringify(all))
}

function buildResearchPrompt(topic: string, engine: string): string {
  return `请对以下主题进行深度研究：

主题：${topic}

搜索引擎偏好：${engine === "advanced" ? "高级搜索，优先学术和权威来源" : "标准搜索"}

请根据主题的复杂度，将研究分解为若干个子任务（简单主题2-3个，复杂主题4-6个），每个子任务聚焦一个具体研究方向，子任务之间不重叠。
对每个子任务，请：
1. 通过搜索获取最新信息，记录实际检索词和来源URL
2. 核实2-4个可靠来源，注明发布日期
3. 形成该方向的简要总结，以笔记形式保存

完成所有子任务后，汇总各方向发现，形成结构化研究报告，包含核心结论与参考来源。`
}

export default function DeepResearch() {
  const [sessions, setSessions] = useState<ResearchSession[]>([])
  const [openId, setOpenId] = useState<string | null>(null)
  const [topicDraft, setTopicDraft] = useState("")
  const [engine, setEngine] = useState<"advanced" | "standard">("advanced")
  const [running, setRunning] = useState(false)
  const [selectedTaskIndex, setSelectedTaskIndex] = useState<number | null>(null)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [liveTasks, setLiveTasks] = useState<ResearchTask[]>([])
  const [logOpen, setLogOpen] = useState(false)
  const [queriesOpen, setQueriesOpen] = useState(false)
  const [followUpDraft, setFollowUpDraft] = useState("")
  const [instructionOpen, setInstructionOpen] = useState(false)
  const [copiedInstruction, setCopiedInstruction] = useState(false)
  const [, setNow] = useState(() => Date.now())

  const openIdRef = useRef<string | null>(null)
  const runningRef = useRef(false)

  const openSession = sessions.find((s) => s.id === openId) ?? null
  const sessionDone = openSession?.status === "complete"
  // Prefer update_todos tasks (plan mode), fall back to delegate children (subagents mode)
  const todoTasks = openSession ? extractResearchTasks(openSession.messages) : []
  const delegateTasks = openSession ? extractResearchTasksFromDelegates(openSession.messages) : []
  const rawBaseTasks = todoTasks.length > 0 ? todoTasks : delegateTasks
  // If session is complete, any task still "in_progress" or "pending" must actually be done
  const baseTasks = sessionDone
    ? rawBaseTasks.map((t) =>
        t.status === "in_progress" || t.status === "pending"
          ? { ...t, status: "completed" as ResearchTaskStatus }
          : t
      )
    : rawBaseTasks
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

  // Load all saved research sessions from localStorage on mount
  useEffect(() => {
    const savedIds = JSON.parse(localStorage.getItem(RESEARCH_IDS_KEY) ?? "[]") as string[]
    const savedOpen = localStorage.getItem(RESEARCH_OPEN_KEY)
    if (savedIds.length === 0) return
    void (async () => {
      // Fetch session list to get real server-side timestamps (seconds)
      const serverTs: Record<string, number> = {}
      try {
        const listRes = await fetch("/api/sessions", { cache: "no-store" })
        if (listRes.ok) {
          const data = (await listRes.json()) as { sessions?: Array<{ id: string; updated_at?: number }> }
          for (const s of data.sessions ?? []) {
            if (s.id && typeof s.updated_at === "number") {
              serverTs[s.id] = s.updated_at * 1000  // convert to ms
            }
          }
        }
      } catch { /* ignore */ }

      const meta = loadMeta()
      const loaded: ResearchSession[] = []
      for (const id of savedIds) {
        const msgs = await loadSession(id)
        if (!msgs) continue
        const topic = meta[id]?.topic || extractResearchTopic(msgs)
        // Server timestamp is most accurate; fall back to stored meta, then now
        const updated_at = serverTs[id] ?? meta[id]?.updated_at ?? Date.now()
        // Persist correct timestamp so next reload doesn't need server call
        saveMeta(id, { topic, updated_at })
        loaded.push({ id, topic, messages: msgs, status: "complete", updated_at, eventCount: msgs.length })
      }
      if (loaded.length === 0) return
      setSessions(loaded)
      const openTarget = savedOpen && loaded.find((s) => s.id === savedOpen) ? savedOpen : loaded[0].id
      setOpenId(openTarget)
      openIdRef.current = openTarget
    })()
  }, [loadSession])

  // Persist session ID list whenever sessions change
  useEffect(() => {
    const ids = sessions.map((s) => s.id)
    if (ids.length > 0) localStorage.setItem(RESEARCH_IDS_KEY, JSON.stringify(ids))
  }, [sessions])

  // Persist currently open session ID
  useEffect(() => {
    if (openId) localStorage.setItem(RESEARCH_OPEN_KEY, openId)
  }, [openId])

  // Update relative timestamps every minute
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000)
    return () => window.clearInterval(timer)
  }, [])

  async function runSessionStream(id: string, msgRes: Response) {
    const pollTimer = setInterval(async () => {
      if (!runningRef.current) return
      const msgs = await loadSession(id)
      if (msgs) {
        setSessions((prev) => prev.map((s) => s.id === id ? { ...s, messages: msgs } : s))
      }
    }, 2000)

    const { completed, status: runStatus } = await readEventStream(msgRes, (event: StreamEvent) => {
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
        const tid = typeof event.tool_call_id === "string" && event.tool_call_id ? event.tool_call_id : ""
        if (tid) {
          setLiveTasks((prev) => prev.map((t) => t.id === tid ? { ...t, status: "in_progress" as ResearchTaskStatus } : t))
        }
      } else if (!isChild && event.kind === "tool_result") {
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

    // If stream ended without run_result, the backend session may still be running.
    // Poll until the session is no longer in running_id.
    if (!completed) {
      for (let i = 0; i < 60; i++) {
        await new Promise<void>((r) => setTimeout(r, 3000))
        if (!runningRef.current) break
        try {
          const listRes = await fetch("/api/sessions", { cache: "no-store" })
          if (listRes.ok) {
            const data = (await listRes.json()) as { running_id?: string | null }
            if (data.running_id !== id) break
          }
        } catch { break }
      }
    }

    setLiveTasks([])

    const finalStatus: ResearchSessionStatus =
      runStatus === "error" ? "error" : "complete"
    const completedAt = Date.now()
    const msgs = await loadSession(id)
    if (msgs) {
      setSessions((prev) =>
        prev.map((s) =>
          s.id === id
            ? { ...s, messages: msgs, status: finalStatus, eventCount: msgs.length, updated_at: completedAt }
            : s
        )
      )
    } else {
      setSessions((prev) => prev.map((s) => s.id === id ? { ...s, status: finalStatus, updated_at: completedAt } : s))
    }
    setSessions((prev) => {
      const s = prev.find(x => x.id === id)
      if (s) saveMeta(id, { topic: s.topic, updated_at: completedAt })
      return prev
    })
  }

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
      saveMeta(id, { topic: topicDraft.trim(), updated_at: Date.now() })
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

      await runSessionStream(id, msgRes)
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

  async function stopResearch() {
    const id = openIdRef.current
    if (!id) return
    try {
      await fetch(`/api/sessions/${encodeURIComponent(id)}/stop`, { method: "POST" })
    } catch {
      // ignore
    }
  }

  async function sendFollowUp() {
    const text = followUpDraft.trim()
    if (!text || running) return
    const id = openIdRef.current
    if (!id) return

    setRunning(true)
    runningRef.current = true
    setFollowUpDraft("")
    setErrorText(null)
    setSessions((prev) => prev.map((s) => s.id === id ? { ...s, status: "running" } : s))

    try {
      const msgRes = await fetch(`/api/sessions/${encodeURIComponent(id)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      })

      if (!msgRes.ok) {
        const code = await readError(msgRes)
        setErrorText(code)
        setSessions((prev) => prev.map((s) => s.id === id ? { ...s, status: "error" } : s))
        return
      }

      await runSessionStream(id, msgRes)
    } catch (e) {
      setErrorText(String(e))
      setSessions((prev) =>
        prev.map((s) => s.id === id ? { ...s, status: "error" } : s)
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

  function switchSession(id: string) {
    setOpenId(id)
    openIdRef.current = id
    setSelectedTaskIndex(null)
    setLiveTasks([])
    setLogOpen(false)
    setInstructionOpen(false)
  }

  function copyPath(path: string) {
    void navigator.clipboard.writeText(path).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const statusLabel = isRunning
    ? "研究进行中"
    : openSession?.status === "complete"
      ? "研究完成"
      : openSession?.status === "error"
        ? "研究出错"
        : "等待开始"

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
            <div className="research-title-name">
              <strong>deep-research</strong>
              <small>深度研究</small>
            </div>
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
                  className={`research-progress-bar${sessionDone ? " is-done" : ""}`}
                  style={{ width: progress.total > 0 ? `${(progress.done / progress.total) * 100}%` : "0%" }}
                />
              </div>
              <div className="research-progress-label">
                {progress.done} / {progress.total} 任务完成
              </div>
            </>
          )}

          {running ? (
            <button
              type="button"
              className="research-stop-btn"
              onClick={() => void stopResearch()}
            >
              ■ 停止研究
            </button>
          ) : (
            <button
              type="submit"
              className="research-start-btn"
              disabled={!topicDraft.trim()}
            >
              + 开始新研究
            </button>
          )}
        </form>

        {errorText && (
          <div className="research-error">{errorText}</div>
        )}

        {sessions.length > 0 && (
          <div className="research-history">
            <div className="research-history-label">历史研究</div>
            <ul className="research-history-list">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className={`research-history-item ${s.id === openId ? "is-open" : ""}`}
                    onClick={() => switchSession(s.id)}
                  >
                    <span className="research-history-topic">{s.topic || "无标题研究"}</span>
                    <span className={`research-history-status ${s.status}`}>
                      {s.status === "running" ? "运行中" : formatRelativeTime(s.updated_at / 1000)}
                    </span>
                  </button>
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
          <>
            <div className="research-heading">
              <div className="research-heading-row">
                <span className="research-heading-label">研究主题</span>
                <span className="research-heading-title" title={openSession.topic}>
                  {(openSession.topic.split("\n")[0] || "深度研究").slice(0, 80)}
                  {openSession.topic.replace(/\n.*/s, "").length > 80 ? "…" : ""}
                </span>
                {openSession.topic.length > 40 && (
                  <button
                    type="button"
                    className="research-instruction-toggle"
                    onClick={() => setInstructionOpen((v) => !v)}
                  >
                    {instructionOpen ? "▲" : "▼"}
                  </button>
                )}
              </div>
              {instructionOpen && (
                <div className="research-instruction-body">
                  <pre className="research-instruction-text">{openSession.topic}</pre>
                  <button
                    type="button"
                    className="research-instruction-copy"
                    onClick={() => {
                      void navigator.clipboard.writeText(openSession.topic).then(() => {
                        setCopiedInstruction(true)
                        setTimeout(() => setCopiedInstruction(false), 1500)
                      })
                    }}
                  >
                    {copiedInstruction ? "✓ 已复制" : "复制全文"}
                  </button>
                </div>
              )}
            </div>
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
            </div>
          </>
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
              {tasks.length === 0 && (
                <div className="research-no-tasks">
                  {isRunning ? "正在规划研究任务…" : "暂无任务数据"}
                </div>
              )}
              <div className="research-task-cards">
                  {tasks.map((task, i) => (
                    <div
                      key={task.id}
                      className={`research-task-card ${task.status} ${selectedTaskIndex === i ? "is-selected" : ""}`}
                      onClick={() => { setSelectedTaskIndex(selectedTaskIndex === i ? null : i); setQueriesOpen(false) }}
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
            </div>

            {/* Right: task detail */}
            <div className="research-right">
              {selectedTask && taskDetail ? (
                <>
                  <div className="research-detail-title">{selectedTask.title}</div>
                  {selectedTask.description && (
                    <div className="research-detail-desc">{selectedTask.description}</div>
                  )}

                  {taskDetail.summary && (
                    <div className="research-detail-section research-summary-section">
                      <div className="research-detail-section-label">任务总结</div>
                      <div className="research-summary-body">
                        <Markdown text={taskDetail.summary} />
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

                  {taskDetail.queries.length > 0 && (
                    <div className="research-detail-section">
                      <button
                        type="button"
                        className="research-detail-section-label research-queries-toggle"
                        onClick={() => setQueriesOpen((v) => !v)}
                      >
                        查询命令
                        <span className="research-queries-toggle-arrow">{queriesOpen ? "▲" : "▼"}</span>
                        <span className="research-queries-count">{taskDetail.queries.length} 条</span>
                      </button>
                      {queriesOpen && (
                        <div className="research-detail-queries">
                          {taskDetail.queries.map((q, i) => (
                            <span key={i} className="research-query-tag">{q.length > 120 ? q.slice(0, 120) + "…" : q}</span>
                          ))}
                        </div>
                      )}
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

        {/* Follow-up composer */}
        {openSession && (
          <form
            className="research-composer"
            onSubmit={(e) => { e.preventDefault(); void sendFollowUp() }}
          >
            <textarea
              className="research-followup-input"
              placeholder={isRunning ? "研究进行中，请稍候…" : "继续提问或补充研究方向，回车发送…"}
              value={followUpDraft}
              disabled={isRunning}
              rows={2}
              onChange={(e) => setFollowUpDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  void sendFollowUp()
                }
              }}
            />
            <div className="research-composer-actions">
              {isRunning ? (
                <button type="button" className="research-composer-stop" onClick={() => void stopResearch()}>
                  ■ 停止
                </button>
              ) : (
                <button
                  type="submit"
                  className="research-composer-send"
                  disabled={!followUpDraft.trim()}
                >
                  发送
                </button>
              )}
            </div>
          </form>
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

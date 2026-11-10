import { useCallback, useEffect, useRef, useState } from "react"
import type { FormEvent, KeyboardEvent } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import "./App.css"

function Markdown({ text }: { text: string }) {
  if (text === "") return null
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  )
}

type SessionItem = {
  id: string
  title: string
  updated_at: number
}

type ToolCall = {
  id: string
  name: string
}

type ChatMessage = {
  role: string
  content: string
  tool_calls: ToolCall[] | null
  tool_call_id: string | null
  is_error: boolean
}

type LiveTurn = {
  thinking: string
  text: string
  tools: string[]
}

type SessionList = {
  sessions: SessionItem[]
  running_id: string | null
  model: string
}

type StreamEvent = {
  kind?: unknown
  text?: unknown
  name?: unknown
  status?: unknown
}

type RunNote = {
  id: string
  status: string
}

const POLL_MS = 1000
const OPEN_SESSION_KEY = "vector-open-session"

const MODES = [
  { id: "react", label: "ReAct" },
  { id: "plan", label: "PlanAndSolve" },
  { id: "reflect", label: "Reflection" },
] as const

type ModeId = (typeof MODES)[number]["id"]

function parseSessionList(value: unknown): SessionList | null {
  if (!value || typeof value !== "object") return null
  const record = value as Record<string, unknown>
  if (!Array.isArray(record.sessions)) return null
  if (record.running_id !== null && typeof record.running_id !== "string") return null
  const sessions: SessionItem[] = []
  for (const item of record.sessions) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.id !== "string" || typeof row.title !== "string") continue
    sessions.push({
      id: row.id,
      title: row.title,
      updated_at: typeof row.updated_at === "number" ? row.updated_at : 0,
    })
  }
  const runningId = record.running_id
  return {
    sessions,
    running_id: typeof runningId === "string" ? runningId : null,
    model: typeof record.model === "string" ? record.model : "",
  }
}

function normalizeTools(value: unknown): ToolCall[] | null {
  if (value == null) return null
  if (!Array.isArray(value)) return null
  const tools: ToolCall[] = []
  for (const item of value) {
    if (!item || typeof item !== "object") continue
    const record = item as Record<string, unknown>
    tools.push({
      id: typeof record.id === "string" ? record.id : "",
      name: typeof record.name === "string" ? record.name : "",
    })
  }
  return tools
}

function normalizeMessages(value: unknown): ChatMessage[] {
  if (!Array.isArray(value)) return []
  const messages: ChatMessage[] = []
  for (const item of value) {
    if (!item || typeof item !== "object") continue
    const record = item as Record<string, unknown>
    messages.push({
      role: typeof record.role === "string" ? record.role : "",
      content: typeof record.content === "string" ? record.content : "",
      tool_calls: normalizeTools(record.tool_calls),
      tool_call_id: typeof record.tool_call_id === "string" ? record.tool_call_id : null,
      is_error: record.is_error === true,
    })
  }
  return messages
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: unknown }
    if (typeof body.error === "string") return body.error
  } catch {
    // A 4xx without JSON still needs a visible error string.
  }
  return "bad_request"
}

function parseEvent(block: string): StreamEvent | null {
  const line = block
    .split("\n")
    .map((item) => item.trim())
    .find((item) => item.startsWith("data:"))
  if (!line) return null
  try {
    const value = JSON.parse(line.slice(5).trim()) as unknown
    if (!value || typeof value !== "object") return null
    return value as StreamEvent
  } catch {
    return null
  }
}

async function readEventStream(
  response: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<{ completed: boolean; status: string | null }> {
  const reader = response.body?.getReader()
  if (!reader) return { completed: false, status: null }
  const decoder = new TextDecoder()
  let buffer = ""
  let completed = false
  let status: string | null = null

  const applyBlock = (block: string) => {
    const event = parseEvent(block)
    if (!event || typeof event.kind !== "string") return
    onEvent(event)
    if (event.kind === "run_result") {
      completed = true
      status = typeof event.status === "string" ? event.status : ""
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split("\n\n")
      buffer = parts.pop() ?? ""
      for (const part of parts) applyBlock(part)
    }
    buffer += decoder.decode()
    if (buffer.trim()) applyBlock(buffer)
  } catch {
    // Dropped before run_result: the caller polls instead of resending.
  }
  return { completed, status }
}

function userMessage(text: string): ChatMessage {
  return {
    role: "user",
    content: text,
    tool_calls: null,
    tool_call_id: null,
    is_error: false,
  }
}

export default function App() {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [runningId, setRunningId] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState("")
  const [readingStream, setReadingStream] = useState(false)
  const [streamSessionId, setStreamSessionId] = useState<string | null>(null)
  const [live, setLive] = useState<LiveTurn | null>(null)
  const [runNote, setRunNote] = useState<RunNote | null>(null)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [listReady, setListReady] = useState(false)
  const [mode, setMode] = useState<ModeId>("react")
  const [modelName, setModelName] = useState("")

  const openIdRef = useRef<string | null>(null)
  const readingStreamRef = useRef(false)
  const sendingRef = useRef(false)
  const streamSessionRef = useRef<string | null>(null)
  const creatingRef = useRef(false)
  const messagesRef = useRef<ChatMessage[]>([])
  const cacheRef = useRef(new Map<string, ChatMessage[]>())
  const bottomRef = useRef<HTMLDivElement | null>(null)
  messagesRef.current = messages

  const refreshList = useCallback(async (): Promise<SessionList | null> => {
    try {
      const response = await fetch("/api/sessions", { cache: "no-store" })
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) {
          setErrorText(await readError(response))
        }
        return null
      }
      const data = parseSessionList(await response.json())
      if (!data) return null
      setSessions(data.sessions)
      setRunningId(data.running_id)
      setModelName(data.model)
      return data
    } catch {
      return null
    } finally {
      setListReady(true)
    }
  }, [])

  const fetchSessionMessages = useCallback(async (id: string): Promise<ChatMessage[] | null> => {
    const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      cache: "no-store",
    })
    if (!response.ok) {
      if (response.status >= 400 && response.status < 500) {
        const code = await readError(response)
        setErrorText(code)
        if (code !== "busy") await refreshList()
      }
      return null
    }
    const body = (await response.json()) as { messages?: unknown }
    return normalizeMessages(body.messages)
  }, [refreshList])

  useEffect(() => {
    void (async () => {
      const data = await refreshList()
      const saved = sessionStorage.getItem(OPEN_SESSION_KEY)
      if (!data || !saved || !data.sessions.some((item) => item.id === saved)) return
      rememberOpen(saved)
      const loaded = await fetchSessionMessages(saved)
      if (!loaded || openIdRef.current !== saved) return
      cacheRef.current.set(saved, loaded)
      setMessages(loaded)
    })()
  }, [refreshList, fetchSessionMessages])

  useEffect(() => {
    if (openId) sessionStorage.setItem(OPEN_SESSION_KEY, openId)
  }, [openId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [messages, live, openId])

  useEffect(() => {
    if (readingStream || runningId === null) return
    let stopped = false
    let pending = false
    const timer = window.setInterval(() => {
      if (pending) return
      pending = true
      void (async () => {
        try {
          const data = await refreshList()
          if (!data || stopped || readingStreamRef.current) return
          if (data.running_id !== null) return
          const current = openIdRef.current
          if (!current) {
            setLive(null)
            streamSessionRef.current = null
            setStreamSessionId(null)
            setErrorText((prev) => (prev === "busy" ? null : prev))
            return
          }
          const loaded = await fetchSessionMessages(current)
          if (readingStreamRef.current) return
          if (loaded && openIdRef.current === current) {
            cacheRef.current.set(current, loaded)
            setMessages(loaded)
            setLive(null)
            streamSessionRef.current = null
            setStreamSessionId(null)
            setErrorText((prev) => (prev === "busy" ? null : prev))
          }
        } finally {
          pending = false
        }
      })()
    }, POLL_MS)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [readingStream, runningId, refreshList, fetchSessionMessages])

  function rememberOpen(id: string) {
    openIdRef.current = id
    setOpenId(id)
  }

  async function selectSession(id: string) {
    const previous = openIdRef.current
    if (previous && previous !== id) cacheRef.current.set(previous, messagesRef.current)
    rememberOpen(id)
    setErrorText(null)
    if (readingStreamRef.current && streamSessionRef.current === id) {
      const cached = cacheRef.current.get(id)
      if (cached) setMessages(cached)
      return
    }
    const loaded = await fetchSessionMessages(id)
    if (!loaded || openIdRef.current !== id) return
    if (readingStreamRef.current && streamSessionRef.current === id) {
      const cached = cacheRef.current.get(id)
      if (cached) setMessages(cached)
      return
    }
    cacheRef.current.set(id, loaded)
    setMessages(loaded)
  }

  async function createSession() {
    if (creatingRef.current) return
    creatingRef.current = true
    try {
      const response = await fetch("/api/sessions", { method: "POST" })
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) {
          setErrorText(await readError(response))
          await refreshList()
        }
        return
      }
      const body = (await response.json()) as { id?: unknown }
      if (typeof body.id !== "string") return
      const id = body.id
      rememberOpen(id)
      const empty: ChatMessage[] = []
      messagesRef.current = empty
      cacheRef.current.set(id, empty)
      setMessages(empty)
      setErrorText(null)
      setSessions((current) =>
        current.some((item) => item.id === id)
          ? current
          : [{ id, title: id, updated_at: Date.now() }, ...current],
      )
      await refreshList()
    } catch {
      setErrorText("error")
    } finally {
      creatingRef.current = false
    }
  }

  function appendDelta(kind: "thinking" | "text" | "tool", piece: string) {
    setLive((prev) => {
      const base = prev ?? { thinking: "", text: "", tools: [] }
      if (kind === "thinking") return { ...base, thinking: base.thinking + piece }
      if (kind === "text") return { ...base, text: base.text + piece }
      if (!piece) return base
      return { ...base, tools: [...base.tools, piece] }
    })
  }

  async function rollbackSend(sessionId: string, text: string) {
    if (openIdRef.current === sessionId) {
      setMessages((current) => {
        const next = [...current]
        const last = next[next.length - 1]
        if (last?.role === "user" && last.content === text) next.pop()
        return next
      })
    }
    setDraft((current) => (current.trim() === "" ? text : current))
    setLive(null)
    streamSessionRef.current = null
    setStreamSessionId(null)
  }

  async function noteRejectedSend(sessionId: string, code: string | null) {
    const listed = await refreshList()
    if (code === "busy" && listed === null) {
      setRunningId((current) => current ?? sessionId)
    }
  }

  async function stopRun() {
    const sessionId = runningId ?? openId
    if (!sessionId) return
    try {
      await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/stop`, { method: "POST" })
    } catch {
      setErrorText("bad_request")
    }
  }

  async function send() {
    const text = draft
    if (text.trim() === "") return
    if (!openId || runningId !== null || readingStream || sendingRef.current) return
    const sessionId = openId
    sendingRef.current = true
    readingStreamRef.current = true
    streamSessionRef.current = sessionId
    setReadingStream(true)
    setDraft("")
    setErrorText(null)
    setRunNote((prev) => (prev?.id === sessionId ? null : prev))
    setMessages((current) => {
      const next = [...current, userMessage(text)]
      cacheRef.current.set(sessionId, next)
      messagesRef.current = next
      return next
    })
    setLive({ thinking: "", text: "", tools: [] })
    setStreamSessionId(sessionId)

    try {
      let response: Response
      try {
        response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, mode }),
        })
      } catch {
        await rollbackSend(sessionId, text)
        await noteRejectedSend(sessionId, null)
        return
      }

      if (!response.ok) {
        const code = response.status >= 400 && response.status < 500 ? await readError(response) : null
        if (code) setErrorText(code)
        await rollbackSend(sessionId, text)
        await noteRejectedSend(sessionId, code)
        return
      }

      setRunningId(sessionId)

      const { completed, status } = await readEventStream(response, (event) => {
        if (event.kind === "text_delta" && typeof event.text === "string") {
          appendDelta("text", event.text)
        } else if (event.kind === "thinking_delta" && typeof event.text === "string") {
          appendDelta("thinking", event.text)
        } else if (event.kind === "tool_call_end" && typeof event.name === "string") {
          appendDelta("tool", event.name)
        }
      })

      if (completed) {
        const loaded = await fetchSessionMessages(sessionId)
        await refreshList()
        if (loaded) {
          cacheRef.current.set(sessionId, loaded)
          if (openIdRef.current === sessionId) setMessages(loaded)
          setLive(null)
          streamSessionRef.current = null
          setStreamSessionId(null)
        }
        if (status && status !== "complete") setRunNote({ id: sessionId, status })
        else setRunNote((prev) => (prev?.id === sessionId ? null : prev))
        return
      }

      const listed = await refreshList()
      if (listed && listed.running_id === null) {
        const current = openIdRef.current
        if (current) {
          const loaded = await fetchSessionMessages(current)
          if (loaded && openIdRef.current === current) {
            cacheRef.current.set(current, loaded)
            setMessages(loaded)
            setLive(null)
            streamSessionRef.current = null
            setStreamSessionId(null)
          }
        } else {
          setLive(null)
          streamSessionRef.current = null
          setStreamSessionId(null)
        }
      }
    } finally {
      readingStreamRef.current = false
      setReadingStream(false)
      sendingRef.current = false
    }
  }

  function onDraftKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return
    if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
    event.preventDefault()
    void send()
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void send()
  }

  const openSession = sessions.find((session) => session.id === openId) ?? null
  const inputLocked = runningId !== null || readingStream
  const showLive =
    live !== null &&
    streamSessionId !== null &&
    streamSessionId === openId &&
    (live.thinking !== "" || live.text !== "" || live.tools.length > 0)
  const visibleStatus =
    runNote && runNote.id === openId && runNote.status !== "complete" ? runNote.status : null

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Vector Harness</div>
        <button type="button" className="new-session" onClick={() => void createSession()}>
          <span className="plus" aria-hidden="true">
            +
          </span>
          新会话
        </button>
        <div className="side-label">会话</div>
        <ul className="session-list">
          {sessions.map((session) => {
            const open = session.id === openId
            const running = session.id === runningId
            const className = [
              "session-item",
              open ? "is-open" : "",
              running ? "is-running" : "",
            ]
              .filter(Boolean)
              .join(" ")
            return (
              <li key={session.id}>
                <button
                  type="button"
                  className={className}
                  aria-current={open ? "true" : undefined}
                  onClick={() => void selectSession(session.id)}
                >
                  <span className="session-title">{session.title}</span>
                  {running ? <span className="running-mark">运行中</span> : null}
                </button>
              </li>
            )
          })}
        </ul>
      </aside>
      <main className="main">
        <header className="topbar">
          <h1 className="current-title">{openSession ? openSession.title : "会话"}</h1>
          {modelName ? (
            <div className="model-name" title={modelName}>
              {modelName}
            </div>
          ) : null}
        </header>
        {errorText ? <div className="error-banner">{errorText}</div> : null}
        {listReady && sessions.length === 0 ? (
          <div className="empty">先新建</div>
        ) : (
          <>
            <div className="transcript">
              <div className="column">
                {openId ? (
                  messages.map((message, index) => (
                    <article
                      key={`${index}-${message.role}`}
                      className={`message-row ${message.role}${message.is_error ? " is-error" : ""}`}
                    >
                      <div className="bubble">
                        {message.role === "tool" && message.is_error ? (
                          <div className="fail">失败</div>
                        ) : null}
                        {message.role === "tool" ? (
                          <pre className="tool-output">{message.content}</pre>
                        ) : (
                          <Markdown text={message.content} />
                        )}
                        {message.tool_calls?.map((call, callIndex) => (
                          <div key={`${call.id}-${callIndex}`} className="tool-name">
                            {call.name}
                          </div>
                        ))}
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="pick">从左侧打开一个会话</div>
                )}
                {showLive && live ? (
                  <article className="message-row assistant">
                    <div className="bubble">
                      {live.thinking ? (
                        <div className="thinking">
                          <Markdown text={live.thinking} />
                        </div>
                      ) : null}
                      <Markdown text={live.text} />
                      {live.tools.map((name, index) => (
                        <div key={`${name}-${index}`} className="tool-name">
                          {name}
                        </div>
                      ))}
                    </div>
                  </article>
                ) : null}
                <div ref={bottomRef} />
              </div>
            </div>
            {visibleStatus ? (
              <div className="status-wrap">
                <div className="status-banner">{visibleStatus === "stopped" ? "已停止" : visibleStatus}</div>
              </div>
            ) : null}
            {openId ? (
              <form className="composer" onSubmit={onSubmit}>
                <div className="composer-row">
                  <textarea
                    value={draft}
                    placeholder="输入消息，回车发送"
                    disabled={inputLocked}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={onDraftKeyDown}
                  />
                  {inputLocked ? (
                    <button type="button" className="send is-stop" aria-label="停止" onClick={() => void stopRun()}>
                      <svg viewBox="0 0 16 16" aria-hidden="true">
                        <rect x="4.5" y="4.5" width="7" height="7" rx="1" />
                      </svg>
                    </button>
                  ) : (
                    <button
                      type="submit"
                      className="send"
                      aria-label="发送"
                      disabled={draft.trim() === ""}
                    >
                      <svg viewBox="0 0 16 16" aria-hidden="true">
                        <path d="M8 12.5V3.5M8 3.5L4 7.5M8 3.5L12 7.5" />
                      </svg>
                    </button>
                  )}
                </div>
                <div className="modes" role="radiogroup" aria-label="模式">
                  {MODES.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={item.id === mode ? "mode is-selected" : "mode"}
                      role="radio"
                      aria-checked={item.id === mode}
                      disabled={inputLocked}
                      onClick={() => setMode(item.id)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </form>
            ) : null}
          </>
        )}
      </main>
    </div>
  )
}

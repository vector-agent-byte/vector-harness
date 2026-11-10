import { useCallback, useEffect, useRef, useState } from "react"
import type { FormEvent, KeyboardEvent, MouseEvent } from "react"
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
  skill: string | null
  started_at: number | null
  duration_ms: number | null
}

type SkillItem = {
  name: string
  description: string
}

type DirEntry = {
  name: string
  path: string
}

type DirListing = {
  path: string
  parent: string | null
  dirs: DirEntry[]
  files: DirEntry[]
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
  created_at: number | null
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
      skill: typeof row.skill === "string" && row.skill !== "" ? row.skill : null,
      started_at: typeof row.started_at === "number" ? row.started_at : null,
      duration_ms: typeof row.duration_ms === "number" ? row.duration_ms : null,
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
      created_at: typeof record.created_at === "number" ? record.created_at : null,
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

function formatClock(seconds: number): string {
  const date = new Date(seconds * 1000)
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function formatDuration(ms: number): string {
  const safe = Math.max(0, Math.round(ms))
  if (safe < 1000) return `${safe}毫秒`
  const totalSeconds = Math.round(safe / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes === 0) return `${seconds}秒`
  return `${minutes}分${String(seconds).padStart(2, "0")}秒`
}

function timingLabel(
  session: SessionItem,
  running: boolean,
  now: number,
): string | null {
  if (session.started_at === null) return null
  const trigger = `${formatClock(session.started_at)} 触发`
  const elapsed = running
    ? Math.max(0, now - session.started_at * 1000)
    : session.duration_ms
  if (elapsed === null) return trigger
  return `${trigger} · 耗时 ${formatDuration(elapsed)}`
}

type SessionMenu = {
  id: string
  x: number
  y: number
}

function sessionProperties(session: SessionItem, running: boolean, now: number) {
  if (session.started_at === null) {
    return { trigger: "还没有运行", duration: "还没有运行" }
  }
  const elapsed = running ? Math.max(0, now - session.started_at * 1000) : session.duration_ms
  return {
    trigger: formatClock(session.started_at),
    duration: elapsed === null ? "还在运行" : formatDuration(elapsed),
  }
}

function viewedPath(root: string, current: string): string {
  const sep = current.includes("\\") ? "\\" : "/"
  const prefix = root.replace(/[\\/]+$/, "") + sep
  if (current.toLowerCase().startsWith(prefix.toLowerCase())) return current.slice(prefix.length)
  const name = current.split(/[\\/]/).filter(Boolean).pop()
  return name || current
}

function errorLabel(code: string): string {
  if (code === "busy") return "正在运行"
  if (code === "not_a_directory") return "不是文件夹"
  if (code === "unknown_skill") return "没有这个技能"
  return code
}

function parseSkills(value: unknown): SkillItem[] {
  if (!value || typeof value !== "object") return []
  const record = value as Record<string, unknown>
  if (!Array.isArray(record.skills)) return []
  const skills: SkillItem[] = []
  for (const item of record.skills) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.name !== "string" || typeof row.description !== "string") continue
    skills.push({ name: row.name, description: row.description })
  }
  return skills
}

function parseEntries(value: unknown): DirEntry[] {
  if (!Array.isArray(value)) return []
  const entries: DirEntry[] = []
  for (const item of value) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.name !== "string" || typeof row.path !== "string") continue
    entries.push({ name: row.name, path: row.path })
  }
  return entries
}

function parseDirs(value: unknown): DirListing | null {
  if (!value || typeof value !== "object") return null
  const record = value as Record<string, unknown>
  if (typeof record.path !== "string" || !Array.isArray(record.dirs)) return null
  return {
    path: record.path,
    parent: typeof record.parent === "string" ? record.parent : null,
    dirs: parseEntries(record.dirs),
    files: parseEntries(record.files),
  }
}

function userMessage(text: string): ChatMessage {
  return {
    role: "user",
    content: text,
    tool_calls: null,
    tool_call_id: null,
    is_error: false,
    created_at: Date.now() / 1000,
  }
}

function messageTimeLabel(message: ChatMessage, sentAt: number | null): string | null {
  if (message.created_at === null) return null
  if (message.role !== "user" && message.role !== "assistant") return null
  const clock = formatClock(message.created_at)
  if (message.role === "assistant" && sentAt !== null) {
    return `${clock} · 耗时 ${formatDuration((message.created_at - sentAt) * 1000)}`
  }
  return clock
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
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [workdir, setWorkdir] = useState("")
  const [pickerOpen, setPickerOpen] = useState(false)
  const [browse, setBrowse] = useState<DirListing | null>(null)
  const [pickerBrowse, setPickerBrowse] = useState<DirListing | null>(null)
  const [pickerError, setPickerError] = useState<string | null>(null)
  const [pathDraft, setPathDraft] = useState("")
  const [skillOpen, setSkillOpen] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [sessionMenu, setSessionMenu] = useState<SessionMenu | null>(null)
  const [propsId, setPropsId] = useState<string | null>(null)

  const openIdRef = useRef<string | null>(null)
  const readingStreamRef = useRef(false)
  const sendingRef = useRef(false)
  const streamSessionRef = useRef<string | null>(null)
  const creatingRef = useRef(false)
  const messagesRef = useRef<ChatMessage[]>([])
  const cacheRef = useRef(new Map<string, ChatMessage[]>())
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
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

  const loadSkills = useCallback(async () => {
    try {
      const response = await fetch("/api/skills", { cache: "no-store" })
      if (!response.ok) return
      setSkills(parseSkills(await response.json()))
    } catch {
      setSkills([])
    }
  }, [])

  const loadDirs = useCallback(async (path: string, target: "view" | "picker" = "view") => {
    const query = path === "" ? "" : `?path=${encodeURIComponent(path)}`
    try {
      const response = await fetch(`/api/dirs${query}`, { cache: "no-store" })
      if (!response.ok) {
        const code = response.status >= 400 && response.status < 500 ? await readError(response) : "bad_request"
        if (target === "picker") setPickerError(errorLabel(code))
        else setErrorText(code)
        return
      }
      const listing = parseDirs(await response.json())
      if (!listing) return
      if (target === "picker") {
        setPickerError(null)
        setPickerBrowse(listing)
        setPathDraft(listing.path)
        return
      }
      setBrowse(listing)
      setPathDraft(listing.path)
    } catch {
      setErrorText("bad_request")
    }
  }, [])

  useEffect(() => {
    void (async () => {
      await loadSkills()
      try {
        const response = await fetch("/api/workdir", { cache: "no-store" })
        if (response.ok) {
          const body = (await response.json()) as { path?: unknown }
          if (typeof body.path === "string") {
            setWorkdir(body.path)
            await loadDirs(body.path)
          }
        }
      } catch {
        // The session list still works if the directory label fails to load.
      }
      const data = await refreshList()
      const saved = sessionStorage.getItem(OPEN_SESSION_KEY)
      if (!data || !saved || !data.sessions.some((item) => item.id === saved)) return
      rememberOpen(saved)
      const loaded = await fetchSessionMessages(saved)
      if (!loaded || openIdRef.current !== saved) return
      cacheRef.current.set(saved, loaded)
      setMessages(loaded)
    })()
  }, [refreshList, fetchSessionMessages, loadSkills, loadDirs])

  useEffect(() => {
    if (openId) sessionStorage.setItem(OPEN_SESSION_KEY, openId)
  }, [openId])

  useEffect(() => {
    if (propsId === null && !pickerOpen) return
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") return
      if (pickerOpen) setPickerOpen(false)
      else setPropsId(null)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [propsId, pickerOpen])

  useEffect(() => {
    if (sessionMenu === null) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target
      if (target instanceof Node && menuRef.current?.contains(target)) return
      setSessionMenu(null)
    }
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setSessionMenu(null)
    }
    function closeMenu() {
      setSessionMenu(null)
    }
    window.addEventListener("pointerdown", onPointerDown)
    window.addEventListener("keydown", onKey)
    window.addEventListener("scroll", closeMenu, true)
    return () => {
      window.removeEventListener("pointerdown", onPointerDown)
      window.removeEventListener("keydown", onKey)
      window.removeEventListener("scroll", closeMenu, true)
    }
  }, [sessionMenu])

  useEffect(() => {
    if (runningId === null) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [runningId])

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

  async function chooseSkill(name: string | null) {
    const sessionId = openIdRef.current
    if (!sessionId || runningId !== null || readingStreamRef.current) return
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/skill`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) setErrorText(await readError(response))
        return
      }
      const body = (await response.json()) as { skill?: unknown }
      const skill = typeof body.skill === "string" && body.skill !== "" ? body.skill : null
      setSessions((current) =>
        current.map((item) => (item.id === sessionId ? { ...item, skill } : item)),
      )
      setErrorText(null)
      setSkillOpen(false)
    } catch {
      setErrorText("bad_request")
    }
  }

  async function openPicker() {
    setPickerOpen(true)
    setPickerError(null)
    setSkillOpen(false)
    await loadDirs(workdir, "picker")
  }

  async function useDirectory(path: string) {
    if (runningId !== null || readingStreamRef.current) {
      setErrorText("busy")
      return
    }
    try {
      const response = await fetch("/api/workdir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      })
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) setErrorText(await readError(response))
        return
      }
      const body = (await response.json()) as { path?: unknown }
      if (typeof body.path !== "string") return
      setWorkdir(body.path)
      setPickerOpen(false)
      setErrorText(null)
      await loadDirs(body.path)
    } catch {
      setErrorText("bad_request")
    }
  }

  async function deleteSession(id: string) {
    if (runningId === id || (readingStreamRef.current && streamSessionRef.current === id)) {
      setErrorText("busy")
      setSessionMenu(null)
      return
    }
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" })
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) setErrorText(await readError(response))
        return
      }
      setSessions((current) => current.filter((item) => item.id !== id))
      cacheRef.current.delete(id)
      if (openIdRef.current === id) {
        openIdRef.current = null
        setOpenId(null)
        setMessages([])
        setLive(null)
        setSkillOpen(false)
        sessionStorage.removeItem(OPEN_SESSION_KEY)
      }
      setErrorText(null)
      setSessionMenu(null)
      if (propsId === id) setPropsId(null)
    } catch {
      setErrorText("bad_request")
    }
  }

  function openSessionMenu(event: MouseEvent<HTMLElement>, id: string) {
    event.preventDefault()
    const width = 140
    const height = 76
    setSessionMenu({
      id,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8)),
    })
  }

  async function selectSession(id: string) {
    setSkillOpen(false)
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
          : [{ id, title: id, updated_at: Date.now(), skill: null, started_at: null, duration_ms: null }, ...current],
      )
      setSkillOpen(false)
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
      setNow(Date.now())
      setSessions((current) =>
        current.map((item) =>
          item.id === sessionId
            ? { ...item, started_at: Date.now() / 1000, duration_ms: null }
            : item,
        ),
      )

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
  const selectedSkill = openSession?.skill ?? null
  const openTiming =
    openSession === null ? null : timingLabel(openSession, openSession.id === runningId, now)
  const propsSession = sessions.find((session) => session.id === propsId) ?? null
  const propsTiming = propsSession
    ? sessionProperties(propsSession, propsSession.id === runningId, now)
    : null
  const inputLocked = runningId !== null || readingStream
  const showLive =
    live !== null &&
    streamSessionId !== null &&
    streamSessionId === openId &&
    (live.thinking !== "" || live.text !== "" || live.tools.length > 0)
  const visibleStatus =
    runNote && runNote.id === openId && runNote.status !== "complete" ? runNote.status : null
  const liveSentAt = [...messages]
    .reverse()
    .find((item) => item.role === "user" && item.created_at !== null)?.created_at
  const liveTiming =
    liveSentAt == null
      ? null
      : `${formatClock(now / 1000)} · 耗时 ${formatDuration(Math.max(0, now - liveSentAt * 1000))}`
  const viewed = browse && workdir && browse.path !== workdir ? viewedPath(workdir, browse.path) : null

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
              <li
                key={session.id}
                className={className}
                onContextMenu={(event) => openSessionMenu(event, session.id)}
              >
                <button
                  type="button"
                  className="session-open"
                  aria-current={open ? "true" : undefined}
                  onClick={() => void selectSession(session.id)}
                >
                  <span className="session-title">
                    {session.title}
                    {session.skill ? <span className="session-skill">{session.skill}</span> : null}
                  </span>
                  {running ? <span className="running-mark">运行中</span> : null}
                </button>
              </li>
            )
          })}
        </ul>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="title-block">
            <h1 className="current-title">{openSession ? openSession.title : "会话"}</h1>
            {openTiming ? <div className="run-time">{openTiming}</div> : null}
          </div>
        </header>
        {errorText ? <div className="error-banner">{errorLabel(errorText)}</div> : null}
        {listReady && sessions.length === 0 ? (
          <div className="empty">先新建</div>
        ) : (
          <>
            <div className="transcript">
              <div className="column">
                {openId ? (
                  messages.map((message, index) => {
                    const sentAt = [...messages.slice(0, index)]
                      .reverse()
                      .find((item) => item.role === "user" && item.created_at !== null)?.created_at ?? null
                    const timeLabel = messageTimeLabel(message, sentAt)
                    return (
                      <article
                        key={`${index}-${message.role}`}
                        className={`message-row ${message.role}${message.is_error ? " is-error" : ""}`}
                      >
                        <div className="message-stack">
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
                          {timeLabel ? <div className="message-time">{timeLabel}</div> : null}
                        </div>
                      </article>
                    )
                  })
                ) : (
                  <div className="pick">从左侧打开一个会话</div>
                )}
                {showLive && live ? (
                  <article className="message-row assistant">
                    <div className="message-stack">
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
                      {liveTiming ? <div className="message-time">{liveTiming}</div> : null}
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
                <div className="composer-tools">
                <div className="skill-row">
                  <button
                    type="button"
                    className={selectedSkill ? "mode is-selected" : "mode"}
                    disabled={inputLocked}
                    aria-expanded={skillOpen}
                    onClick={() => setSkillOpen((open) => !open)}
                  >
                    {selectedSkill ? `技能 · ${selectedSkill}` : "选择技能"}
                  </button>
                  {skillOpen ? (
                    <div className="skill-menu" role="listbox" aria-label="技能">
                      <button
                        type="button"
                        className={selectedSkill === null ? "skill-option is-selected" : "skill-option"}
                        onClick={() => void chooseSkill(null)}
                      >
                        <span className="skill-name">不使用</span>
                      </button>
                      {skills.map((skill) => (
                        <button
                          key={skill.name}
                          type="button"
                          className={
                            skill.name === selectedSkill ? "skill-option is-selected" : "skill-option"
                          }
                          onClick={() => void chooseSkill(skill.name)}
                        >
                          <span className="skill-name">{skill.name}</span>
                          <span className="skill-description">{skill.description}</span>
                        </button>
                      ))}
                      {skills.length === 0 ? <div className="skill-empty">没有可选择的技能</div> : null}
                    </div>
                  ) : null}
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
                {modelName ? (
                  <div className="composer-model" title={modelName}>
                    {modelName}
                  </div>
                ) : null}
                </div>
              </form>
            ) : null}
          </>
        )}
      </main>
      <aside className="workdir-panel">
        <button
          type="button"
          className="workdir-button"
          title={workdir}
          disabled={inputLocked}
          onClick={() => void openPicker()}
        >
          <span className="workdir-kicker">工作目录</span>
          <span className="workdir-path">{workdir || "选择目录"}</span>
        </button>
        {viewed && browse ? (
          <div className="viewed-path" title={browse.path}>
            {viewed}
          </div>
        ) : null}
        {browse ? (
          <ul className="dir-list" aria-label="目录内容">
            {browse.parent ? (
              <li className="is-up">
                <button type="button" onClick={() => browse.parent && void loadDirs(browse.parent)}>
                  ..
                </button>
              </li>
            ) : null}
            {browse.dirs.map((dir) => (
              <li key={dir.path} className="is-dir">
                <button type="button" onClick={() => void loadDirs(dir.path)}>
                  {dir.name}
                </button>
              </li>
            ))}
            {browse.files.map((file) => (
              <li key={file.path} className="is-file">
                <span>{file.name}</span>
              </li>
            ))}
            {browse.dirs.length === 0 && browse.files.length === 0 ? (
              <li className="is-empty">这个目录是空的</li>
            ) : null}
          </ul>
        ) : null}
      </aside>
      {pickerOpen && pickerBrowse ? (
        <div className="props-backdrop" onClick={() => setPickerOpen(false)}>
          <div
            className="picker-dialog"
            role="dialog"
            aria-label="选择工作目录"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading">选择工作目录</div>
            <form
              className="dir-jump"
              onSubmit={(event) => {
                event.preventDefault()
                void loadDirs(pathDraft, "picker")
              }}
            >
              <input
                value={pathDraft}
                aria-label="文件夹路径"
                onChange={(event) => setPathDraft(event.target.value)}
              />
              <button type="submit">前往</button>
            </form>
            {pickerError ? <div className="picker-error">{pickerError}</div> : null}
            <ul className="dir-list picker-list" aria-label="可选目录">
              {pickerBrowse.parent ? (
                <li className="is-up">
                  <button type="button" onClick={() => pickerBrowse.parent && void loadDirs(pickerBrowse.parent, "picker")}>
                    ..
                  </button>
                </li>
              ) : null}
              {pickerBrowse.dirs.map((dir) => (
                <li key={dir.path} className="is-dir">
                  <button type="button" onClick={() => void loadDirs(dir.path, "picker")}>
                    {dir.name}
                  </button>
                </li>
              ))}
              {pickerBrowse.dirs.length === 0 ? <li className="is-empty">没有子文件夹</li> : null}
            </ul>
            <div className="dir-actions">
              <button type="button" onClick={() => setPickerOpen(false)}>
                取消
              </button>
              <button type="button" onClick={() => void useDirectory(pickerBrowse.path)}>
                使用此目录
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {sessionMenu ? (
        <div
          ref={menuRef}
          className="session-menu"
          role="menu"
          style={{ left: sessionMenu.x, top: sessionMenu.y }}
        >
          <button
            type="button"
            role="menuitem"
            disabled={sessionMenu.id === runningId}
            onClick={() => void deleteSession(sessionMenu.id)}
          >
            删除
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setPropsId(sessionMenu.id)
              setSessionMenu(null)
            }}
          >
            查看属性
          </button>
        </div>
      ) : null}
      {propsSession ? (
        <div
          className="props-backdrop"
          onClick={() => setPropsId(null)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setPropsId(null)
          }}
        >
          <div
            className="props-card"
            role="dialog"
            aria-label="会话属性"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading">属性</div>
            <dl>
              <dt>标题</dt>
              <dd>{propsSession.title}</dd>
              <dt>技能</dt>
              <dd>{propsSession.skill ?? "未选择"}</dd>
              <dt>触发</dt>
              <dd>{propsTiming?.trigger}</dd>
              <dt>耗时</dt>
              <dd>{propsTiming?.duration}</dd>
            </dl>
            <button type="button" className="props-close" onClick={() => setPropsId(null)}>
              关闭
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

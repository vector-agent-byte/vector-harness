import { useCallback, useEffect, useRef, useState } from "react"
import type { CSSProperties, FormEvent, KeyboardEvent, MouseEvent, PointerEvent as ReactPointerEvent } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { entryMenu as entryMenuLabels, findListableDir, highlightCode, listingIsCurrent, refreshMayReplaceDraft, REFRESH_MS, shouldShowPicker } from "./dirPath.ts"
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

type EntryKind = "file" | "dir"

type EntryMenu = {
  kind: EntryKind
  name: string
  path: string
  x: number
  y: number
}

type FilePreview = {
  name: string
  path: string
  kind: "text" | "image" | "too_large" | "unsupported"
  text: string
}

type NamedPath = {
  name: string
  path: string
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
  if (code === "not_a_file") return "不是文件"
  if (code === "bad_name") return "名字不合法"
  if (code === "exists") return "已经有同名项"
  if (code === "not_found") return "没有找到"
  if (code === "bad_path") return "不能改这个位置"
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

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function userPreview(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim()
  if (flat.length <= 72) return flat
  return `${flat.slice(0, 72)}…`
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
  const [entryMenu, setEntryMenu] = useState<EntryMenu | null>(null)
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [renameTarget, setRenameTarget] = useState<(NamedPath & { draft: string }) | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<NamedPath | null>(null)
  const [propsId, setPropsId] = useState<string | null>(null)
  const [userMarks, setUserMarks] = useState<{ index: number; top: number; label: string }[]>([])
  const [activeUser, setActiveUser] = useState<number | null>(null)
  const [locatedUser, setLocatedUser] = useState<number | null>(null)
  const [dialogOffset, setDialogOffset] = useState({ x: 0, y: 0 })
  const [dialogSize, setDialogSize] = useState<{ width: number; height: number } | null>(null)

  const openIdRef = useRef<string | null>(null)
  const readingStreamRef = useRef(false)
  const sendingRef = useRef(false)
  const streamSessionRef = useRef<string | null>(null)
  const creatingRef = useRef(false)
  const messagesRef = useRef<ChatMessage[]>([])
  const cacheRef = useRef(new Map<string, ChatMessage[]>())
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const locatedTimer = useRef<number | null>(null)
  const dialogOffsetRef = useRef(dialogOffset)
  const dialogGesture = useRef<
    | { kind: "drag"; x: number; y: number; ox: number; oy: number; left: number; top: number }
    | { kind: "resize"; x: number; y: number; width: number; height: number; left: number; top: number }
    | null
  >(null)
  dialogOffsetRef.current = dialogOffset
  const menuRef = useRef<HTMLDivElement | null>(null)
  const entryMenuRef = useRef<HTMLDivElement | null>(null)
  const viewedPathRef = useRef("")
  const pickerOpenRef = useRef(false)
  const workdirRef = useRef("")
  messagesRef.current = messages
  pickerOpenRef.current = pickerOpen
  workdirRef.current = workdir

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

  const loadDirs = useCallback(async (
    path: string,
    target: "view" | "picker" = "view",
    replaceDraft = true,
  ): Promise<DirListing | null> => {
    if (target === "view") viewedPathRef.current = path
    const query = path === "" ? "" : `?path=${encodeURIComponent(path)}`
    try {
      const response = await fetch(`/api/dirs${query}`, { cache: "no-store" })
      if (!response.ok) {
        const code = response.status >= 400 && response.status < 500 ? await readError(response) : "bad_request"
        if (target === "picker") setPickerError(errorLabel(code))
        else setErrorText(code)
        return null
      }
      const listing = parseDirs(await response.json())
      if (!listing) return null
      if (target === "picker") {
        setPickerError(null)
        setPickerBrowse(listing)
        setPathDraft(listing.path)
        return listing
      }
      if (!listingIsCurrent(path, viewedPathRef.current)) return null
      viewedPathRef.current = listing.path
      setBrowse(listing)
      if (replaceDraft && refreshMayReplaceDraft(pickerOpenRef.current)) setPathDraft(listing.path)
      return listing
    } catch {
      setErrorText("bad_request")
      return null
    }
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (pickerOpenRef.current) return
      const path = viewedPathRef.current || workdirRef.current
      if (path === "") return
      void loadDirs(path, "view", refreshMayReplaceDraft(false))
    }, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [loadDirs])

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
    if (entryMenu === null) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target
      if (target instanceof Node && entryMenuRef.current?.contains(target)) return
      setEntryMenu(null)
    }
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setEntryMenu(null)
    }
    window.addEventListener("pointerdown", onPointerDown)
    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("pointerdown", onPointerDown)
      window.removeEventListener("keydown", onKey)
    }
  }, [entryMenu])

  useEffect(() => {
    if (runningId === null) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [runningId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [messages, live, openId])

  const dialogKey = pickerOpen
    ? "picker"
    : preview
      ? "preview"
      : renameTarget
        ? "rename"
        : deleteTarget
          ? "delete"
          : propsId
            ? "props"
            : ""

  useEffect(() => {
    setDialogOffset({ x: 0, y: 0 })
    setDialogSize(null)
  }, [dialogKey])

  useEffect(() => {
    function onMove(event: PointerEvent) {
      const start = dialogGesture.current
      if (!start) return
      if (start.kind === "drag") {
        const left = clamp(start.left + event.clientX - start.x, 8, window.innerWidth - 48)
        const top = clamp(start.top + event.clientY - start.y, 8, window.innerHeight - 48)
        const next = { x: start.ox + left - start.left, y: start.oy + top - start.top }
        dialogOffsetRef.current = next
        setDialogOffset(next)
        return
      }
      const width = clamp(start.width + event.clientX - start.x, 260, Math.max(260, window.innerWidth - start.left - 8))
      const height = clamp(start.height + event.clientY - start.y, 140, Math.max(140, window.innerHeight - start.top - 8))
      const next = {
        x: start.left - (window.innerWidth - width) / 2,
        y: start.top - (window.innerHeight - height) / 2,
      }
      dialogOffsetRef.current = next
      setDialogOffset(next)
      setDialogSize({ width, height })
    }
    function onUp() {
      dialogGesture.current = null
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
    }
  }, [])

  function beginDialogDrag(event: ReactPointerEvent<HTMLElement>) {
    if (event.button !== 0) return
    const dialog = event.currentTarget.closest(".picker-dialog, .props-card")
    if (!(dialog instanceof HTMLElement)) return
    const rect = dialog.getBoundingClientRect()
    const offset = dialogOffsetRef.current
    dialogGesture.current = {
      kind: "drag",
      x: event.clientX,
      y: event.clientY,
      ox: offset.x,
      oy: offset.y,
      left: rect.left,
      top: rect.top,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function beginDialogResize(event: ReactPointerEvent<HTMLElement>) {
    if (event.button !== 0) return
    event.stopPropagation()
    event.preventDefault()
    const dialog = event.currentTarget.closest(".picker-dialog, .props-card")
    if (!(dialog instanceof HTMLElement)) return
    const rect = dialog.getBoundingClientRect()
    dialogGesture.current = {
      kind: "resize",
      x: event.clientX,
      y: event.clientY,
      width: rect.width,
      height: rect.height,
      left: rect.left,
      top: rect.top,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function dialogFrame(className: string): { className: string; style: CSSProperties } {
    const style: CSSProperties = { transform: `translate(${dialogOffset.x}px, ${dialogOffset.y}px)` }
    if (dialogSize) {
      style.width = dialogSize.width
      style.height = dialogSize.height
    }
    return { className: dialogSize ? `${className} is-sized` : className, style }
  }

  useEffect(() => {
    const root = transcriptRef.current
    if (!root) return
    let frame = 0
    const measure = () => {
      const nodes = [...root.querySelectorAll<HTMLElement>("[data-user-message]")]
      const height = root.scrollHeight
      const rootTop = root.getBoundingClientRect().top
      const next = nodes.map((node) => {
        const topPx = node.getBoundingClientRect().top - rootTop + root.scrollTop
        const raw = height <= 0 ? 0 : (topPx / height) * 100
        return {
          index: Number(node.dataset.userMessage),
          top: Math.min(98, Math.max(1, raw)),
          label: node.dataset.label ?? "",
        }
      })
      setUserMarks((current) => {
        if (
          current.length === next.length &&
          current.every(
            (item, index) =>
              item.index === next[index].index &&
              item.label === next[index].label &&
              Math.abs(item.top - next[index].top) < 0.25,
          )
        ) {
          return current
        }
        return next
      })
      const line = root.scrollTop + 24
      let active: number | null = null
      for (const node of nodes) {
        const topPx = node.getBoundingClientRect().top - rootTop + root.scrollTop
        if (topPx <= line) active = Number(node.dataset.userMessage)
      }
      setActiveUser((current) => (current === active ? current : active))
    }
    const schedule = () => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(measure)
    }
    schedule()
    const observer = new ResizeObserver(schedule)
    observer.observe(root)
    const column = root.querySelector(".column")
    if (column) observer.observe(column)
    root.addEventListener("scroll", schedule, { passive: true })
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
      root.removeEventListener("scroll", schedule)
    }
  }, [messages, live, openId])

  function jumpToUser(index: number) {
    const root = transcriptRef.current
    const node = root?.querySelector<HTMLElement>(`[data-user-message="${index}"]`)
    if (!root || !node) return
    const top = node.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop
    const next = top - root.clientHeight / 2 + node.offsetHeight / 2
    root.scrollTo({ top: Math.max(0, next), behavior: "smooth" })
    setLocatedUser(index)
    if (locatedTimer.current !== null) window.clearTimeout(locatedTimer.current)
    locatedTimer.current = window.setTimeout(() => {
      setLocatedUser((current) => (current === index ? null : current))
      locatedTimer.current = null
    }, 1400)
  }

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

  function refreshListing() {
    const path = viewedPathRef.current || workdirRef.current
    if (path === "") return
    void loadDirs(path, "view", refreshMayReplaceDraft(pickerOpenRef.current))
  }

  function openEntryMenu(event: MouseEvent<HTMLElement>, kind: EntryKind, name: string, path: string) {
    event.preventDefault()
    event.stopPropagation()
    const labels = entryMenuLabels(kind)
    const width = 140
    const height = labels.length * 32 + 12
    setEntryMenu({
      kind,
      name,
      path,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8)),
    })
  }

  async function openPreview(path: string, name: string) {
    setEntryMenu(null)
    try {
      const response = await fetch(`/api/file?path=${encodeURIComponent(path)}`, { cache: "no-store" })
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) setErrorText(await readError(response))
        return
      }
      const body = (await response.json()) as { kind?: unknown; text?: unknown }
      const kind = body.kind
      if (kind !== "text" && kind !== "image" && kind !== "too_large" && kind !== "unsupported") return
      setPreview({
        name,
        path,
        kind,
        text: typeof body.text === "string" ? body.text : "",
      })
    } catch {
      setErrorText("bad_request")
    }
  }

  function downloadEntry(path: string) {
    setEntryMenu(null)
    const link = document.createElement("a")
    link.href = `/api/file/bytes?path=${encodeURIComponent(path)}`
    document.body.append(link)
    link.click()
    link.remove()
  }

  async function submitRename() {
    if (renameTarget === null) return
    try {
      const response = await fetch("/api/file/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: renameTarget.path, name: renameTarget.draft }),
      })
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) setErrorText(await readError(response))
        return
      }
      setRenameTarget(null)
      setErrorText(null)
      refreshListing()
    } catch {
      setErrorText("bad_request")
    }
  }

  async function confirmDelete() {
    if (deleteTarget === null) return
    try {
      const response = await fetch("/api/file", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: deleteTarget.path }),
      })
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) setErrorText(await readError(response))
        return
      }
      setDeleteTarget(null)
      setErrorText(null)
      refreshListing()
    } catch {
      setErrorText("bad_request")
    }
  }

  function chooseEntryAction(label: string, menu: EntryMenu) {
    if (label === "查看") {
      void openPreview(menu.path, menu.name)
      return
    }
    if (label === "下载") {
      downloadEntry(menu.path)
      return
    }
    if (label === "重命名") {
      setEntryMenu(null)
      setRenameTarget({ name: menu.name, path: menu.path, draft: menu.name })
      return
    }
    if (label === "删除") {
      setEntryMenu(null)
      setDeleteTarget({ name: menu.name, path: menu.path })
    }
  }

  async function openPicker() {
    setPickerOpen(true)
    setPickerError(null)
    setSkillOpen(false)
    setPathDraft(workdir)
    const found = await findListableDir(workdir, async (path) => (await loadDirs(path, "picker")) !== null)
    if (!found) {
      setPickerError("不是文件夹")
      return
    }
    if (found.relocated) setPickerError("原来的工作目录已经不在，请另选一个文件夹。")
  }

  async function chooseDirectory(path: string) {
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
          </div>
        </header>
        {errorText ? <div className="error-banner">{errorLabel(errorText)}</div> : null}
        {listReady && sessions.length === 0 ? (
          <div className="empty">先新建</div>
        ) : (
          <>
            <div className="transcript-wrap">
            <div className="transcript" ref={transcriptRef}>
              <div className="column">
                {openId ? (
                  messages.map((message, index) => {
                    const sentAt = [...messages.slice(0, index)]
                      .reverse()
                      .find((item) => item.role === "user" && item.created_at !== null)?.created_at ?? null
                    const timeLabel = messageTimeLabel(message, sentAt)
                    const isUser = message.role === "user"
                    return (
                      <article
                        key={`${index}-${message.role}`}
                        className={`message-row ${message.role}${message.is_error ? " is-error" : ""}${locatedUser === index ? " is-located" : ""}`}
                        data-user-message={isUser ? index : undefined}
                        data-label={isUser ? userPreview(message.content) : undefined}
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
            {userMarks.length > 0 ? (
              <div className="user-rail" aria-label="用户输入">
                {userMarks.map((mark) => (
                  <button
                    key={mark.index}
                    type="button"
                    className={mark.index === activeUser ? "user-mark is-active" : "user-mark"}
                    style={{ top: `${mark.top}%` }}
                    data-label={mark.label}
                    title={mark.label}
                    aria-label={mark.label === "" ? "用户输入" : mark.label}
                    onClick={() => jumpToUser(mark.index)}
                  />
                ))}
              </div>
            ) : null}
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
        <div className="workdir-card">
          <div className="workdir-head">
            <span className="workdir-kicker">工作目录</span>
            <button type="button" className="workdir-refresh" aria-label="刷新" title="刷新" onClick={() => refreshListing()}>
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M2.6 8a5.4 5.4 0 0 1 9.1-4" />
                <path d="M11.7 2.4v3.1H8.6" />
                <path d="M13.4 8a5.4 5.4 0 0 1-9.1 4" />
                <path d="M4.3 13.6V10.5H7.4" />
              </svg>
            </button>
          </div>
          <button
            type="button"
            className="workdir-button"
            title={workdir}
            disabled={inputLocked}
            onClick={() => void openPicker()}
          >
            <span className="workdir-path">{workdir || "选择目录"}</span>
          </button>
        </div>
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
                <button
                  type="button"
                  onClick={() => void loadDirs(dir.path)}
                  onContextMenu={(event) => openEntryMenu(event, "dir", dir.name, dir.path)}
                >
                  {dir.name}
                </button>
              </li>
            ))}
            {browse.files.map((file) => (
              <li key={file.path} className="is-file">
                <button
                  type="button"
                  onClick={() => void openPreview(file.path, file.name)}
                  onContextMenu={(event) => openEntryMenu(event, "file", file.name, file.path)}
                >
                  {file.name}
                </button>
              </li>
            ))}
            {browse.dirs.length === 0 && browse.files.length === 0 ? (
              <li className="is-empty">这个目录是空的</li>
            ) : null}
          </ul>
        ) : null}
      </aside>
      {shouldShowPicker(pickerOpen, pickerBrowse !== null) ? (
        <div className="props-backdrop" onClick={() => setPickerOpen(false)}>
          <div
            {...dialogFrame("picker-dialog")}
            role="dialog"
            aria-label="选择工作目录"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>选择工作目录</div>
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
              {pickerBrowse?.parent ? (
                <li className="is-up">
                  <button type="button" onClick={() => pickerBrowse.parent && void loadDirs(pickerBrowse.parent, "picker")}>
                    ..
                  </button>
                </li>
              ) : null}
              {pickerBrowse
                ? pickerBrowse.dirs.map((dir) => (
                    <li key={dir.path} className="is-dir">
                      <button type="button" onClick={() => void loadDirs(dir.path, "picker")}>
                        {dir.name}
                      </button>
                    </li>
                  ))
                : null}
              {pickerBrowse && pickerBrowse.dirs.length === 0 ? <li className="is-empty">没有子文件夹</li> : null}
              {!pickerBrowse ? <li className="is-empty">{pickerError ? "没有可显示的文件夹" : "正在读取"}</li> : null}
            </ul>
            <div className="dir-actions">
              <button type="button" onClick={() => setPickerOpen(false)}>
                取消
              </button>
              <button
                type="button"
                disabled={pickerBrowse === null}
                onClick={() => {
                  if (pickerBrowse === null) return
                  void chooseDirectory(pickerBrowse.path)
                }}
              >
                使用此目录
              </button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
      {entryMenu ? (
        <div
          ref={entryMenuRef}
          className="session-menu"
          role="menu"
          style={{ left: entryMenu.x, top: entryMenu.y }}
        >
          {entryMenuLabels(entryMenu.kind).map((label) => (
            <button key={label} type="button" role="menuitem" onClick={() => chooseEntryAction(label, entryMenu)}>
              {label}
            </button>
          ))}
        </div>
      ) : null}
      {preview ? (
        <div className="props-backdrop" onClick={() => setPreview(null)}>
          <div
            {...dialogFrame("picker-dialog file-preview")}
            role="dialog"
            aria-label="查看文件"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>{preview.name}</div>
            {preview.kind === "text" ? (
              <pre className="preview-text">
                {highlightCode(preview.text, preview.name).map((token, index) =>
                  token.kind === "plain" ? (
                    token.text
                  ) : (
                    <span key={index} className={`tok-${token.kind}`}>
                      {token.text}
                    </span>
                  ),
                )}
              </pre>
            ) : null}
            {preview.kind === "image" ? (
              <img
                className="preview-image"
                alt={preview.name}
                src={`/api/file/bytes?path=${encodeURIComponent(preview.path)}&inline=1`}
              />
            ) : null}
            {preview.kind === "too_large" ? <p className="picker-error">这个文件超过 2MB，不能预览</p> : null}
            {preview.kind === "unsupported" ? <p className="picker-error">这个文件不能预览</p> : null}
            <div className="dir-actions">
              <button type="button" onClick={() => setPreview(null)}>
                取消
              </button>
              <button type="button" onClick={() => downloadEntry(preview.path)}>
                下载
              </button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
      {renameTarget ? (
        <div className="props-backdrop" onClick={() => setRenameTarget(null)}>
          <form
            {...dialogFrame("picker-dialog")}
            aria-label="重命名"
            onClick={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault()
              void submitRename()
            }}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>重命名</div>
            <input
              className="rename-input"
              aria-label="新名称"
              value={renameTarget.draft}
              onChange={(event) =>
                setRenameTarget((current) => (current ? { ...current, draft: event.target.value } : current))
              }
            />
            <div className="dir-actions">
              <button type="button" onClick={() => setRenameTarget(null)}>
                取消
              </button>
              <button type="submit">确定</button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </form>
        </div>
      ) : null}
      {deleteTarget ? (
        <div className="props-backdrop" onClick={() => setDeleteTarget(null)}>
          <div
            {...dialogFrame("picker-dialog")}
            role="dialog"
            aria-label="删除"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>删除 {deleteTarget.name}？</div>
            <div className="dir-actions">
              <button type="button" onClick={() => setDeleteTarget(null)}>
                取消
              </button>
              <button type="button" onClick={() => void confirmDelete()}>
                删除
              </button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
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
            {...dialogFrame("props-card")}
            role="dialog"
            aria-label="会话属性"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>属性</div>
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
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
    </div>
  )
}

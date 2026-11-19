import { useCallback, useEffect, useRef, useState } from "react"
import type { CSSProperties, FormEvent, KeyboardEvent, MouseEvent, PointerEvent as ReactPointerEvent } from "react"
import { MODES, normalizeMode } from "./modes.ts"
import { updateChildren } from "./children.ts"
import { lastUserMessageTime, messagePresentation } from "./reflection.ts"
import { ChildAgentCard } from "./ChildAgentCard.tsx"
import type { ModeId } from "./modes.ts"
import { sessionSkillSelection, skillSelectionLabel, toggleSkill } from "./skills.ts"
import type { SkillSelection } from "./skills.ts"
import { entryMenu as entryMenuLabels, findListableDir, highlightCode, listingGenerationIsCurrent, refreshMayReplaceDraft, REFRESH_MS, shouldShowPicker, viewedPathAfter } from "./dirPath.ts"
import {
  normalizeMessages,
  normalizeWarnings,
  parseDirs,
  parseSessionList,
  parseSkills,
  readError,
  readEventStream,
} from "./api.ts"
import {
  clamp,
  errorLabel,
  formatClock,
  formatDuration,
  formatRelativeTime,
  messageTimeLabel,
  sessionProperties,
  toolSummary,
  userMessage,
  userPreview,
  viewedPath,
} from "./format.ts"
import {
  ChainView,
  Markdown,
  ReflectionCard,
  StatusNote,
  ThinkingBlock,
  TodoList,
  TraceView,
} from "./components.tsx"
import type {
  ChatMessage,
  DirListing,
  EntryKind,
  EntryMenu,
  FilePreview,
  LiveTurn,
  NamedPath,
  RunNote,
  SessionItem,
  SessionList,
  SessionMenu,
  SkillItem,
  TodoItem,
} from "./types.ts"
import "./App.css"
import DeepResearch from "./DeepResearch.tsx"

const POLL_MS = 1000
const OPEN_SESSION_KEY = "vector-open-session"

export default function App() {
  const [appView, setAppView] = useState<"agent" | "deepresearch">(
    () => (localStorage.getItem("vh-app-view") as "agent" | "deepresearch") ?? "agent"
  )
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
  const [savingMode, setSavingMode] = useState(false)
  const [modelName, setModelName] = useState("")
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [workdir, setWorkdir] = useState("")
  const [pickerOpen, setPickerOpen] = useState(false)
  const [browse, setBrowse] = useState<DirListing | null>(null)
  const [pickerBrowse, setPickerBrowse] = useState<DirListing | null>(null)
  const [pickerError, setPickerError] = useState<string | null>(null)
  const [pathDraft, setPathDraft] = useState("")
  const [skillOpen, setSkillOpen] = useState(false)
  const [skillDraft, setSkillDraft] = useState<SkillSelection>(null)
  const [skillSearch, setSkillSearch] = useState("")
  const [skillError, setSkillError] = useState<string | null>(null)
  const [savingSkills, setSavingSkills] = useState(false)
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
  const [sidebarWidth, setSidebarWidth] = useState(220)
  const [workdirWidth, setWorkdirWidth] = useState(260)
  const [viewMode, setViewMode] = useState<"chat" | "trace" | "chain">("chat")
  const [runnerChain, setRunnerChain] = useState("")
  const [runnerSubagents, setRunnerSubagents] = useState(false)

  const openIdRef = useRef<string | null>(null)
  const readingStreamRef = useRef(false)
  const sendingRef = useRef(false)
  const savingModeRef = useRef(false)
  const savingSkillsRef = useRef(false)
  const skillSessionRef = useRef<string | null>(null)
  const settingsRevisionRef = useRef(0)
  const streamSessionRef = useRef<string | null>(null)
  const creatingRef = useRef(false)
  const pendingToolsRef = useRef(0)
  const resetLiveRef = useRef(false)
  const lastOriginRef = useRef<string>("")
  const messagesRef = useRef<ChatMessage[]>([])
  const cacheRef = useRef(new Map<string, ChatMessage[]>())
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const prevOpenIdRef = useRef<string | null>(null)
  const isNearBottomRef = useRef(true)
  const locatedTimer = useRef<number | null>(null)
  const dialogOffsetRef = useRef(dialogOffset)
  const dialogGesture = useRef<
    | { kind: "drag"; x: number; y: number; ox: number; oy: number; left: number; top: number }
    | { kind: "resize"; x: number; y: number; width: number; height: number; left: number; top: number }
    | null
  >(null)
  dialogOffsetRef.current = dialogOffset
  const panelResizeRef = useRef<{ panel: "sidebar" | "workdir"; startX: number; startWidth: number } | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const entryMenuRef = useRef<HTMLDivElement | null>(null)
  const viewedPathRef = useRef("")
  const viewGenerationRef = useRef(0)
  const pickerOpenRef = useRef(false)
  const workdirRef = useRef("")
  messagesRef.current = messages
  pickerOpenRef.current = pickerOpen
  workdirRef.current = workdir

  const refreshList = useCallback(async (): Promise<SessionList | null> => {
    const settingsRevision = settingsRevisionRef.current
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
      if (settingsRevision === settingsRevisionRef.current && !savingModeRef.current && !savingSkillsRef.current) setSessions(data.sessions)
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
    const settingsRevision = settingsRevisionRef.current
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
    const body = (await response.json()) as Record<string, unknown>
    if (settingsRevision === settingsRevisionRef.current && !savingModeRef.current && !savingSkillsRef.current) {
      setSessions(current => current.map(item => item.id === id ? { ...item, mode: normalizeMode(body.mode), skills: sessionSkillSelection(body) } : item))
    }
    const warnings = normalizeWarnings(body.warnings)
    if (settingsRevision === settingsRevisionRef.current && openIdRef.current === id) {
      setErrorText(current => openIdRef.current === id
        ? warnings[0] ?? (current?.startsWith("session_") ? null : current)
        : current)
    }
    if (openIdRef.current === id && typeof body.runner_chain === "string") {
      setRunnerChain(body.runner_chain)
      setRunnerSubagents(body.subagents === true)
    }
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
    const generation = target === "view" ? (viewGenerationRef.current += 1) : 0
    const query = path === "" ? "" : `?path=${encodeURIComponent(path)}`
    try {
      const response = await fetch(`/api/dirs${query}`, { cache: "no-store" })
      if (!response.ok) {
        const code = response.status >= 400 && response.status < 500 ? await readError(response) : "bad_request"
        if (target === "picker") setPickerError(errorLabel(code))
        else if (listingGenerationIsCurrent(generation, viewGenerationRef.current)) setErrorText(code)
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
      if (!listingGenerationIsCurrent(generation, viewGenerationRef.current)) return null
      viewedPathRef.current = viewedPathAfter(viewedPathRef.current, listing.path)
      setBrowse(listing)
      if (replaceDraft && refreshMayReplaceDraft(pickerOpenRef.current)) setPathDraft(listing.path)
      return listing
    } catch {
      if (target !== "picker" && listingGenerationIsCurrent(generation, viewGenerationRef.current)) {
        setErrorText("bad_request")
      }
      return null
    }
  }, [])

  useEffect(() => {
    localStorage.setItem("vh-app-view", appView)
  }, [appView])

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
    if (!skillOpen) return
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && !savingSkillsRef.current) setSkillOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [skillOpen])

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
    const transcript = transcriptRef.current
    const sessionChanged = prevOpenIdRef.current !== openId
    prevOpenIdRef.current = openId
    if (sessionChanged) {
      isNearBottomRef.current = true
    }
    if (!transcript) return
    if (isNearBottomRef.current) {
      transcript.scrollTop = transcript.scrollHeight
    }
  }, [messages, live, openId])

  const dialogKey = skillOpen ? "skills" : pickerOpen
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
      const drag = panelResizeRef.current
      if (drag) {
        const delta = event.clientX - drag.startX
        if (drag.panel === "sidebar") {
          setSidebarWidth(clamp(drag.startWidth + delta, 140, 480))
        } else {
          setWorkdirWidth(clamp(drag.startWidth - delta, 160, 520))
        }
        return
      }
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
      panelResizeRef.current = null
      dialogGesture.current = null
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
    }
  }, [])

  function beginPanelResize(event: ReactPointerEvent<HTMLDivElement>, panel: "sidebar" | "workdir") {
    event.preventDefault()
    panelResizeRef.current = {
      panel,
      startX: event.clientX,
      startWidth: panel === "sidebar" ? sidebarWidth : workdirWidth,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

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
    const trackBottom = () => {
      const { scrollTop, scrollHeight, clientHeight } = root
      isNearBottomRef.current = scrollHeight - scrollTop - clientHeight < 120
    }
    root.addEventListener("scroll", schedule, { passive: true })
    root.addEventListener("scroll", trackBottom, { passive: true })
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
      root.removeEventListener("scroll", schedule)
      root.removeEventListener("scroll", trackBottom)
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
          const current = openIdRef.current
          if (data.running_id !== null) {
            // Run still in progress: reload messages to show real-time tool results
            if (!current) return
            const loaded = await fetchSessionMessages(current)
            if (!readingStreamRef.current && loaded && openIdRef.current === current) {
              cacheRef.current.set(current, loaded)
              setMessages(loaded)
            }
            return
          }
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

  async function chooseMode(mode: ModeId) {
    const sessionId = openIdRef.current
    if (!sessionId || runningId !== null || readingStreamRef.current || sendingRef.current || savingModeRef.current || savingSkillsRef.current) return
    savingModeRef.current = true
    settingsRevisionRef.current += 1
    setSavingMode(true)
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      })
      if (!response.ok) {
        setErrorText(await readError(response))
        return
      }
      const body = (await response.json()) as { mode?: unknown }
      setSessions(current => current.map(item => item.id === sessionId ? { ...item, mode: normalizeMode(body.mode) } : item))
      setErrorText(null)
    } catch {
      setErrorText("bad_request")
    } finally {
      settingsRevisionRef.current += 1
      savingModeRef.current = false
      setSavingMode(false)
    }
  }

  function openSkillPicker() {
    if (!openSession || inputLocked) return
    skillSessionRef.current = openSession.id
    setSkillDraft(openSession.skills === null ? null : [...openSession.skills])
    setSkillSearch("")
    setSkillError(null)
    setSkillOpen(true)
    void loadSkills()
  }

  async function saveSkills() {
    const sessionId = skillSessionRef.current
    if (!sessionId || runningId !== null || readingStreamRef.current || sendingRef.current || savingSkillsRef.current || savingModeRef.current) return
    savingSkillsRef.current = true
    settingsRevisionRef.current += 1
    setSavingSkills(true)
    setSkillError(null)
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/skills`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ names: skillDraft }),
      })
      if (!response.ok) {
        setSkillError(errorLabel(await readError(response)))
        return
      }
      const body = (await response.json()) as Record<string, unknown>
      setSessions((current) =>
        current.map((item) => (item.id === sessionId ? { ...item, skills: sessionSkillSelection(body) } : item)),
      )
      setErrorText(null)
      setSkillOpen(false)
    } catch {
      setSkillError("技能选择保存失败，请重试")
    } finally {
      settingsRevisionRef.current += 1
      savingSkillsRef.current = false
      setSavingSkills(false)
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
        setErrorText(await readError(response))
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
        setErrorText(await readError(response))
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
    pickerOpenRef.current = true
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
        setErrorText(await readError(response))
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
    setRunnerChain("")
    setRunnerSubagents(false)
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
          : [{ id, title: id, updated_at: Date.now(), skills: null, mode: "react", started_at: null, duration_ms: null }, ...current],
      )
      setSkillOpen(false)
      await refreshList()
    } catch {
      setErrorText("error")
    } finally {
      creatingRef.current = false
    }
  }

  function appendDelta(kind: "thinking" | "text" | "tool", piece: string, toolArgs?: Record<string, unknown> | null) {
    lastOriginRef.current = ""
    setLive((prev) => {
      const base = prev ?? { thinking: "", text: "", tools: [], children: [] }
      if (kind === "thinking") return { ...base, thinking: base.thinking + piece }
      if (kind === "text") return { ...base, text: base.text + piece }
      if (!piece) return base
      return { ...base, tools: [...base.tools, { name: piece, args: toolArgs ?? null }] }
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
    if (!openId || runningId !== null || readingStream || sendingRef.current || savingModeRef.current || savingSkillsRef.current) return
    const sessionId = openId
    sendingRef.current = true
    readingStreamRef.current = true
    streamSessionRef.current = sessionId
    pendingToolsRef.current = 0
    resetLiveRef.current = false
    prevOpenIdRef.current = null
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
    lastOriginRef.current = ""
    setLive({ thinking: "", text: "", tools: [], children: [] })
    setStreamSessionId(sessionId)

    try {
      let response: Response
      try {
        response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
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
        const origin = typeof event.origin === "string" ? event.origin : undefined
        const isChild = origin === "child"
        setLive(prev => {
          const base = prev ?? { thinking: "", text: "", tools: [], children: [] }
          const children = updateChildren(base.children, event)
          return children === base.children ? prev : { ...base, children }
        })
        if (isChild) {
          lastOriginRef.current = "child"
          return
        }
        if (event.kind === "text_delta" && typeof event.text === "string") {
          if (resetLiveRef.current && !isChild) {
            resetLiveRef.current = false
            lastOriginRef.current = ""
            const t = event.text as string
            setLive(prev => ({ thinking: "", text: t, tools: [], children: prev?.children ?? [] }))
          } else {
            appendDelta("text", event.text)
          }
        } else if (event.kind === "thinking_delta" && typeof event.text === "string") {
          if (resetLiveRef.current && !isChild) {
            resetLiveRef.current = false
            lastOriginRef.current = ""
            const t = event.text as string
            setLive(prev => ({ thinking: t, text: "", tools: [], children: prev?.children ?? [] }))
          } else {
            appendDelta("thinking", event.text)
          }
        } else if (event.kind === "tool_call_end" && typeof event.name === "string") {
          if (!isChild) pendingToolsRef.current += 1
          const args =
            event.arguments && typeof event.arguments === "object"
              ? (event.arguments as Record<string, unknown>)
              : null
          appendDelta("tool", event.name, args)
        } else if (event.kind === "tool_result" && !isChild) {
          pendingToolsRef.current = Math.max(0, pendingToolsRef.current - 1)
          if (pendingToolsRef.current === 0) {
            resetLiveRef.current = true
            void (async () => {
              const loaded = await fetchSessionMessages(sessionId)
              if (loaded && openIdRef.current === sessionId) {
                cacheRef.current.set(sessionId, loaded)
                setMessages(loaded)
              }
            })()
          }
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
  const selectedSkills = openSession?.skills ?? null
  const skillOptions = [
    ...skills,
    ...(skillDraft ?? []).filter(name => !skills.some(skill => skill.name === name))
      .map(name => ({ name, description: "当前不可用，请取消选择后保存" })),
  ].filter(skill => `${skill.name} ${skill.description}`.toLowerCase().includes(skillSearch.trim().toLowerCase()))
  const mode = openSession?.mode ?? "react"
  const propsSession = sessions.find((session) => session.id === propsId) ?? null
  const propsTiming = propsSession
    ? sessionProperties(propsSession, propsSession.id === runningId, now)
    : null
  const inputLocked = runningId !== null || readingStream || savingMode || savingSkills
  const showLive =
    live !== null &&
    streamSessionId !== null &&
    streamSessionId === openId &&
    (live.thinking !== "" || live.text !== "" || live.tools.length > 0)
  const visibleStatus =
    runNote && runNote.id === openId && runNote.status !== "complete" ? runNote.status : null
  const liveSentAt = lastUserMessageTime(messages)
  const liveTiming =
    liveSentAt == null
      ? null
      : `${formatClock(now / 1000)} · 耗时 ${formatDuration(Math.max(0, now - liveSentAt * 1000))}`
  const viewed = browse && workdir && browse.path !== workdir ? viewedPath(workdir, browse.path) : null

  return (
    <div className="app">
      {/* Activity bar — far-left icon strip */}
      <div className="activity-bar">
        <div className="activity-logo" title="Vector Harness">
          <svg aria-hidden="true" viewBox="0 0 48 46" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path fill="currentColor" d="M25.946 44.938c-.664.845-2.021.375-2.021-.698V33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.947 44.94z"/>
          </svg>
        </div>
        <nav className="activity-nav" aria-label="视图切换">
          <button
            type="button"
            className={appView === "agent" ? "activity-item is-active" : "activity-item"}
            title="智能体"
            aria-label="智能体"
            onClick={() => setAppView("agent")}
          >
            智能体
          </button>
          <button
            type="button"
            className={appView === "deepresearch" ? "activity-item is-active" : "activity-item"}
            title="深度调研"
            aria-label="深度调研"
            onClick={() => setAppView("deepresearch")}
          >
            深度调研
          </button>
        </nav>
      </div>

      {appView === "deepresearch" ? (
        <DeepResearch />
      ) : (
      <>
      <aside className="sidebar" style={{ width: sidebarWidth }}>
        <div className="brand">
          <svg className="brand-icon" aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="7" width="14" height="10" rx="2" />
            <path d="M7 7V5a3 3 0 0 1 6 0v2" />
            <circle cx="7.5" cy="12" r="1" fill="currentColor" stroke="none" />
            <circle cx="12.5" cy="12" r="1" fill="currentColor" stroke="none" />
            <path d="M10 2v2" />
          </svg>
          智能体
        </div>
        <button type="button" className="new-session" onClick={() => void createSession()}>
          <svg className="new-session-icon" aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="6.5" />
            <line x1="8" y1="5" x2="8" y2="11" />
            <line x1="5" y1="8" x2="11" y2="8" />
          </svg>
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
                    <span className="session-skill">{skillSelectionLabel(session.skills)}</span>
                  </span>
                  {running
                    ? <span className="running-mark">运行中</span>
                    : <span className="session-age">{formatRelativeTime(session.updated_at)}</span>
                  }
                </button>
              </li>
            )
          })}
        </ul>
      </aside>
      <div className="panel-resize panel-resize-left" onPointerDown={(e) => beginPanelResize(e, "sidebar")} />
      <main className="main">
        <header className="topbar">
          <div className="title-block">
            <h1 className="current-title">{openSession ? openSession.title : "会话"}</h1>
            {openSession?.started_at != null ? (
              <span className="session-start-time">{formatClock(openSession.started_at)}</span>
            ) : null}
          </div>
        </header>
        {openId ? (
          <div className="view-tabs">
            <button
              type="button"
              className={viewMode === "chat" ? "view-tab is-active" : "view-tab"}
              onClick={() => setViewMode("chat")}
            >
              会话
            </button>
            <button
              type="button"
              className={viewMode === "trace" ? "view-tab is-active" : "view-tab"}
              onClick={() => setViewMode("trace")}
            >
              轨迹
            </button>
            <button
              type="button"
              className={viewMode === "chain" ? "view-tab is-active" : "view-tab"}
              onClick={() => setViewMode("chain")}
            >
              运行链
            </button>
          </div>
        ) : null}
        {errorText ? (
          <div className="error-banner">
            <span className="error-banner-icon" aria-hidden="true">✕</span>
            {errorLabel(errorText)}
          </div>
        ) : null}
        {listReady && sessions.length === 0 ? (
          <div className="empty">先新建</div>
        ) : (
          <>
            <div className="transcript-wrap">
            {viewMode === "chain" ? (
              <ChainView chain={runnerChain} subagents={runnerSubagents} />
            ) : viewMode === "trace" ? (
              <TraceView messages={messages} live={showLive ? live : null} />
            ) : (
            <div className="transcript" ref={transcriptRef}>
              <div className="column">
                {openId ? (() => {
                  const SILENT_TOOLS = new Set(["update_todos", "submit_verdict"])
                  const toolCallNames = new Map<string, string>()
                  for (const msg of messages) {
                    for (const call of msg.tool_calls ?? []) {
                      if (call.id) {
                        toolCallNames.set(call.id, call.name)
                      }
                    }
                  }
                  return messages.flatMap((message, index) => {
                    const hasContent = message.content.trim() !== ""
                    const hasToolCalls = (message.tool_calls?.filter((c) => c.name !== "").length ?? 0) > 0
                    if (!hasContent && !hasToolCalls) return []
                    if (message.role === "tool" && message.tool_call_id) {
                      const calledName = toolCallNames.get(message.tool_call_id)
                      if (calledName && SILENT_TOOLS.has(calledName) && !message.is_error) return []
                    }
                    const sentAt = lastUserMessageTime(messages.slice(0, index))
                    const { role: displayRole, isUser, reflection } = messagePresentation(message)
                    const timeLabel = messageTimeLabel(message, reflection ? null : sentAt)
                    const children = []
                    for (const call of message.tool_calls ?? []) {
                      const childSection = showLive && live?.children.some(child => child.toolCallId === call.id)
                        ? undefined : call.child
                      if (childSection) {
                        children.push(
                          <ChildAgentCard
                            key={`child-saved-${call.id}`}
                            child={childSection}
                            callId={call.id}
                            task={typeof call.args?.task === "string" ? call.args.task : undefined}
                            active={runningId === openId}
                          />
                        )
                      }
                    }
                    const article = (
                      <article
                        key={`${index}-${message.role}`}
                        className={`message-row ${displayRole}${reflection ? " reflection-row" : ""}${message.is_error ? " is-error" : ""}${isUser && locatedUser === index ? " is-located" : ""}`}
                        data-user-message={isUser ? index : undefined}
                        data-label={isUser ? userPreview(message.content) : undefined}
                      >
                        <div className="message-stack">
                          <div className="bubble">
                            {message.role === "tool" && message.is_error ? (
                              <div className="fail">失败</div>
                            ) : null}
                            {reflection ? (
                              <ReflectionCard pass={reflection.pass} text={reflection.text} />
                            ) : message.role === "tool" ? (
                              <pre className="tool-output">{message.content}</pre>
                            ) : <Markdown text={message.content} />}
                            {message.tool_calls?.map((call, callIndex) => {
                              if (!call.name) return null
                              if (call.name === "update_todos" && Array.isArray(call.args?.todos)) {
                                const todos = call.args!.todos as TodoItem[]
                                return <TodoList key={`${call.id}-${callIndex}`} todos={todos} />
                              }
                              if (call.name === "submit_verdict") {
                                const pass = call.args?.pass === true
                                return (
                                  <ReflectionCard key={`${call.id}-${callIndex}`} pass={pass}
                                    text={typeof call.args?.critique === "string" ? call.args.critique : ""} />
                                )
                              }
                              const summary = toolSummary(call.name, call.args)
                              return (
                                <div key={`${call.id}-${callIndex}`} className="tool-name">
                                  <span className="tool-name-label">{call.name}</span>
                                  {summary ? (
                                    <span className="tool-name-arg">{summary.length > 80 ? summary.slice(0, 80) + "…" : summary}</span>
                                  ) : null}
                                </div>
                              )
                            })}
                          </div>
                          {timeLabel ? <div className="message-time">{timeLabel}</div> : null}
                        </div>
                      </article>
                    )
                    return [article, ...children]
                  })
                })() : (
                  <div className="pick">从左侧打开一个会话</div>
                )}
                {showLive && live ? (
                  <article className="message-row assistant">
                    <div className="message-stack">
                      <div className="bubble">
                        {live.thinking ? (
                          <ThinkingBlock text={live.thinking} streaming={readingStream && lastOriginRef.current !== "child"} />
                        ) : null}
                        <Markdown text={live.text} />
                        {live.tools.map((tool, index) => {
                          if (!tool.name) return null
                          if (tool.name === "update_todos" && Array.isArray(tool.args?.todos)) {
                            const todos = tool.args!.todos as TodoItem[]
                            return <TodoList key={`${tool.name}-${index}`} todos={todos} />
                          }
                          if (tool.name === "submit_verdict") {
                            const pass = tool.args?.pass === true
                            return (
                              <ReflectionCard key={`${tool.name}-${index}`} pass={pass}
                                text={typeof tool.args?.critique === "string" ? tool.args.critique : ""} />
                            )
                          }
                          const summary = toolSummary(tool.name, tool.args)
                          return (
                            <div key={`${tool.name}-${index}`} className="tool-name">
                              <span className="tool-name-label">{tool.name}</span>
                              {summary ? (
                                <span className="tool-name-arg">{summary.length > 80 ? summary.slice(0, 80) + "…" : summary}</span>
                              ) : null}
                            </div>
                          )
                        })}
                        {live.children.length > 0 ? (
                          <div className="child-agent-summary" role="status">
                            子代理 {live.children.length} 个 · 运行中 {live.children.filter(child => child.status === "running").length} · 排队中 {live.children.filter(child => child.status === "queued").length}
                          </div>
                        ) : null}
                        <div className="child-agent-grid">
                          {live.children.map(child => (
                            <ChildAgentCard
                              key={child.toolCallId}
                              child={child}
                              callId={child.toolCallId ?? ""}
                              task={child.task}
                              active={runningId === openId || readingStream}
                            />
                          ))}
                        </div>
                      </div>
                      {liveTiming ? <div className="message-time">{liveTiming}</div> : null}
                    </div>
                  </article>
                ) : null}
                <div ref={bottomRef} />
              </div>
            </div>
            )}
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
                <StatusNote status={visibleStatus} />
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
                    className={selectedSkills === null || selectedSkills.length > 0 ? "mode is-selected" : "mode"}
                    disabled={inputLocked || !openId}
                    aria-expanded={skillOpen}
                    aria-haspopup="dialog"
                    onClick={openSkillPicker}
                  >
                    {skillSelectionLabel(selectedSkills)}
                  </button>
                </div>
                <div className="modes" role="radiogroup" aria-label="模式">
                  {MODES.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={item.id === mode ? "mode is-selected" : "mode"}
                      role="radio"
                      aria-checked={item.id === mode}
                      disabled={inputLocked || !openId}
                      onClick={() => void chooseMode(item.id)}
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
      <div className="panel-resize panel-resize-right" onPointerDown={(e) => beginPanelResize(e, "workdir")} />
      <aside className="workdir-panel" style={{ width: workdirWidth }}>
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
            {workdir ? (
              <>
                <span className="workdir-dirname">{workdir.split(/[/\\]/).filter(Boolean).pop() ?? workdir}</span>
                <span className="workdir-path">{workdir}</span>
              </>
            ) : (
              <span className="workdir-path">选择目录</span>
            )}
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
      {skillOpen ? (
        <div className="props-backdrop" onClick={() => { if (!savingSkills) setSkillOpen(false) }}>
          <div
            {...dialogFrame("picker-dialog skills-dialog")}
            role="dialog"
            aria-modal="true"
            aria-labelledby="skills-dialog-title"
            onClick={event => event.stopPropagation()}
          >
            <div id="skills-dialog-title" className="props-heading" onPointerDown={beginDialogDrag}>选择会话技能</div>
            <p className="skills-dialog-hint">技能仅应用于当前会话，保存后刷新或重新打开仍会保留。全选会自动包含新增技能。</p>
            <div className="skills-toolbar">
              <div className="skills-search">
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
                  <circle cx="8.5" cy="8.5" r="5.5" />
                  <path d="m13 13 4 4" />
                </svg>
                <input
                  type="search"
                  aria-label="搜索技能"
                  placeholder="搜索技能名称或说明…"
                  value={skillSearch}
                  onChange={event => setSkillSearch(event.target.value)}
                />
              </div>
              <div className="skills-bulk-actions" role="group" aria-label="批量选择技能">
                <button type="button" aria-pressed={skillDraft === null} disabled={savingSkills} onClick={() => setSkillDraft(null)}>
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="m3 8 3 3 7-7" />
                  </svg>
                  全选
                </button>
                <button type="button" aria-pressed={skillDraft !== null && skillDraft.length === 0} disabled={savingSkills} onClick={() => setSkillDraft([])}>
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
                    <path d="M4 8h8" />
                  </svg>
                  全不选
                </button>
              </div>
            </div>
            <div className="skills-selection-count" aria-live="polite">
              {skillDraft === null ? `已全选 · ${skills.length} 项技能` : `已选择 ${skillDraft.length} 项技能`}
            </div>
            <div className="skills-grid" role="group" aria-label="可选技能">
              {skillOptions.map(skill => {
                const checked = skillDraft === null || skillDraft.includes(skill.name)
                return (
                  <label key={skill.name} className={`skill-card${checked ? " is-selected" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={savingSkills}
                      onChange={() => setSkillDraft(current => toggleSkill(current, skill.name, skills.map(item => item.name)))}
                    />
                    <span className="skill-card-content">
                      <span className="skill-name">{skill.name}</span>
                      <span className="skill-description">{skill.description}</span>
                    </span>
                  </label>
                )
              })}
              {skillOptions.length === 0 ? <div className="skill-empty">{skills.length === 0 ? "没有可选择的技能" : "没有匹配的技能"}</div> : null}
            </div>
            {skillError ? <div className="picker-error" role="alert">{skillError}</div> : null}
            <div className="dir-actions">
              <button type="button" disabled={savingSkills} onClick={() => setSkillOpen(false)}>取消</button>
              <button type="button" className="skills-save" disabled={savingSkills || runningId !== null} onClick={() => void saveSkills()}>
                {savingSkills ? "正在保存…" : "保存选择"}
              </button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
      {shouldShowPicker(pickerOpen, pickerBrowse !== null) ? (
        <div className="props-backdrop" onClick={() => setPickerOpen(false)}>
          <div
            {...dialogFrame("picker-dialog workdir-picker")}
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
              <dd>{propsSession.skills === null ? "全部技能" : propsSession.skills.join("、") || "不使用技能"}</dd>
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
      </>
      )}
    </div>
  )
}

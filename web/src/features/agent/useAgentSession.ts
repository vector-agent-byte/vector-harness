import { useCallback, useEffect, useRef, useState } from "react"
import type { FormEvent, KeyboardEvent, MouseEvent } from "react"
import { normalizeMode } from "../../modes.ts"
import { sessionSkillSelection } from "../../skills.ts"
import { updateChildren } from "../../children.ts"
import { lastUserMessageTime } from "../../reflection.ts"
import { normalizeMessages, normalizeWarnings, parseSessionList, readError } from "../../api.ts"
import { formatClock, formatDuration, sessionProperties, userMessage } from "../../format.ts"
import type { ChatMessage, LiveTurn, RunNote, SessionItem, SessionList, SessionMenu } from "../../types.ts"
import { agentRequests, readEventStream } from "./api.ts"
import { useSessionSettings } from "./useSessionSettings.ts"

const POLL_MS = 1000
const OPEN_SESSION_KEY = "vector-open-session"

export function useAgentSession(homeActive: boolean) {
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
  const [modelName, setModelName] = useState("")
  const [now, setNow] = useState(() => Date.now())
  const [sessionMenu, setSessionMenu] = useState<SessionMenu | null>(null)
  const [propsId, setPropsId] = useState<string | null>(null)
  const [runnerChain, setRunnerChain] = useState("")
  const [runnerSubagents, setRunnerSubagents] = useState(false)

  const openIdRef = useRef<string | null>(null)
  const readingStreamRef = useRef(false)
  const sendingRef = useRef(false)
  const savingModeRef = useRef(false)
  const savingSkillsRef = useRef(false)
  const settingsRevisionRef = useRef(0)
  const streamSessionRef = useRef<string | null>(null)
  const creatingRef = useRef(false)
  const pendingToolsRef = useRef(0)
  const resetLiveRef = useRef(false)
  const lastOriginRef = useRef<string>("")
  const messagesRef = useRef<ChatMessage[]>([])
  const cacheRef = useRef(new Map<string, ChatMessage[]>())
  const menuRef = useRef<HTMLDivElement | null>(null)

  const [scrollRequest, setScrollRequest] = useState(0)
  messagesRef.current = messages
  const refreshList = useCallback(async (): Promise<SessionList | null> => {
    const settingsRevision = settingsRevisionRef.current
    try {
      const response = await agentRequests.listSessions()
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
    const response = await agentRequests.session(id)
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

  useEffect(() => {
    if (!homeActive) return
    void refreshList()
    const timer = window.setInterval(() => void refreshList(), 4000)
    return () => window.clearInterval(timer)
  }, [homeActive, refreshList])

  useEffect(() => {
    void (async () => {
      const data = await refreshList()
      const saved = sessionStorage.getItem(OPEN_SESSION_KEY)
      if (!data || !saved || !data.sessions.some(item => item.id === saved)) return
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

  const openSession = sessions.find(session => session.id === openId) ?? null
  const settings = useSessionSettings({ openSession, openIdRef, runningId, readingStreamRef, sendingRef, savingModeRef, savingSkillsRef, settingsRevisionRef, setSessions, setErrorText })
  const { savingMode, savingSkills, setSkillOpen } = settings
  async function deleteSession(id: string) {
    if (runningId === id || (readingStreamRef.current && streamSessionRef.current === id)) {
      setErrorText("busy")
      setSessionMenu(null)
      return
    }
    try {
      const response = await agentRequests.deleteSession(id)
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
      const response = await agentRequests.createSession()
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
      await agentRequests.stopSession(sessionId)
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
    setScrollRequest(value => value + 1)
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
        response = await agentRequests.sendMessage(sessionId, text)
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

  const selectedSkills = openSession?.skills ?? null
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

  return { sessions, runningId, openId, messages, draft, setDraft, readingStream, readingStreamRef, live, runNote, errorText, setErrorText, listReady, modelName, now, sessionMenu, setSessionMenu, propsId, setPropsId, menuRef, runnerChain, runnerSubagents, lastOriginRef, scrollRequest, openSession, selectedSkills, mode, inputLocked, showLive, visibleStatus, liveTiming, propsSession, propsTiming, createSession, selectSession, deleteSession, openSessionMenu, stopRun, onDraftKeyDown, onSubmit, ...settings }
}

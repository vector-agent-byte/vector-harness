import { useEffect, useRef, useState } from "react"
import type { ChatMessage, LiveTurn } from "../../types.ts"
import type { AppView } from "../../appViews.ts"

type TranscriptContext = {
  messages: ChatMessage[]
  live: LiveTurn | null
  openId: string | null
  appView: AppView
  viewMode: string
  scrollRequest: number
}

export function useTranscriptNavigation({ messages, live, openId, appView, viewMode, scrollRequest }: TranscriptContext) {
  const [userMarks, setUserMarks] = useState<{ index: number; top: number; label: string }[]>([])
  const [activeUser, setActiveUser] = useState<number | null>(null)
  const [locatedUser, setLocatedUser] = useState<number | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const prevOpenIdRef = useRef<string | null>(null)
  const isNearBottomRef = useRef(true)
  const locatedTimer = useRef<number | null>(null)
  const scrollRequestRef = useRef(scrollRequest)
  useEffect(() => {
    const transcript = transcriptRef.current
    const sessionChanged = prevOpenIdRef.current !== openId || scrollRequestRef.current !== scrollRequest
    prevOpenIdRef.current = openId
    scrollRequestRef.current = scrollRequest
    if (sessionChanged) {
      isNearBottomRef.current = true
    }
    if (!transcript) return
    if (isNearBottomRef.current) {
      transcript.scrollTop = transcript.scrollHeight
    }
  }, [messages, live, openId, appView, viewMode, scrollRequest])

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
  }, [messages, live, openId, appView, viewMode])

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

  useEffect(() => () => {
    if (locatedTimer.current !== null) window.clearTimeout(locatedTimer.current)
  }, [])

  return { bottomRef, transcriptRef, userMarks, activeUser, locatedUser, jumpToUser }
}

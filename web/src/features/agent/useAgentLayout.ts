import { useEffect, useRef, useState } from "react"
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react"
import { clamp } from "../../format.ts"

export function useAgentLayout(dialogKey: string) {
  const [dialogOffset, setDialogOffset] = useState({ x: 0, y: 0 })
  const [dialogSize, setDialogSize] = useState<{ width: number; height: number } | null>(null)
  const [workdirWidth, setWorkdirWidth] = useState(260)
  const dialogOffsetRef = useRef(dialogOffset)
  const dialogGesture = useRef<
    | { kind: "drag"; x: number; y: number; ox: number; oy: number; left: number; top: number }
    | { kind: "resize"; x: number; y: number; width: number; height: number; left: number; top: number }
    | null
  >(null)
  dialogOffsetRef.current = dialogOffset
  const panelResizeRef = useRef<{ startX: number; startWidth: number } | null>(null)
  useEffect(() => {
    setDialogOffset({ x: 0, y: 0 })
    setDialogSize(null)
  }, [dialogKey])

  useEffect(() => {
    function onMove(event: PointerEvent) {
      const drag = panelResizeRef.current
      if (drag) {
        const delta = event.clientX - drag.startX
        setWorkdirWidth(clamp(drag.startWidth - delta, 160, 520))
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

  function beginPanelResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault()
    panelResizeRef.current = {
      startX: event.clientX,
      startWidth: workdirWidth,
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


  return { workdirWidth, beginPanelResize, beginDialogDrag, beginDialogResize, dialogFrame }
}

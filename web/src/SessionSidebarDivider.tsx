import {useEffect, useRef, useState} from "react"
import type {PointerEvent} from "react"
import "./SessionSidebarDivider.css"

type Props = {
  sidebarId: string;
  collapsed: boolean;
  onToggle: () => void;
  onResize: (width: number) => void;
}

export default function SessionSidebarDivider({sidebarId, collapsed, onToggle, onResize}: Props) {
  const root = useRef<HTMLDivElement>(null)
  const drag = useRef<{pointerId: number; startX: number; startWidth: number} | null>(null)
  const [measuredWidth, setMeasuredWidth] = useState(0)
  const minWidth = 140
  const maxWidth = 480
  const currentWidth = () => {
    const panel = root.current?.previousElementSibling
    return panel ? parseFloat(getComputedStyle(panel).width) || minWidth : minWidth
  }

  useEffect(() => {
    const panel = root.current?.previousElementSibling
    if (!panel) return
    const observer = new ResizeObserver(() => setMeasuredWidth(parseFloat(getComputedStyle(panel).width) || 0))
    observer.observe(panel)
    return () => observer.disconnect()
  }, [])

  const resize = (width: number) => onResize(Math.min(maxWidth, Math.max(minWidth, width)))
  const finish = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return
    drag.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return <div className="session-sidebar-divider" ref={root}>
    {!collapsed && <div className="panel-resize panel-resize-left" role="separator" aria-label="调整会话列表宽度" aria-orientation="vertical" aria-controls={sidebarId} aria-valuemin={minWidth} aria-valuemax={maxWidth} aria-valuenow={Math.round(measuredWidth)} tabIndex={0}
      onPointerDown={event => {
        if (event.button !== 0) return
        event.preventDefault()
        drag.current = {pointerId: event.pointerId, startX: event.clientX, startWidth: currentWidth()}
        event.currentTarget.setPointerCapture(event.pointerId)
      }}
      onPointerMove={event => {
        const active = drag.current
        if (active?.pointerId === event.pointerId) resize(active.startWidth + event.clientX - active.startX)
      }}
      onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={() => { drag.current = null }}
      onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
        event.preventDefault()
        resize(event.key === "Home" ? minWidth : event.key === "End" ? maxWidth : currentWidth() + (event.key === "ArrowRight" ? 10 : -10))
      }}/>}
    <button type="button" className="sidebar-collapse-button" aria-label={collapsed ? "展开会话列表" : "收起会话列表"} title={collapsed ? "展开会话列表" : "收起会话列表"} aria-controls={sidebarId} aria-expanded={!collapsed} onClick={onToggle}>
      <svg viewBox="0 0 16 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{transform: collapsed ? "rotate(180deg)" : undefined}}><path d="m10 6-5 6 5 6"/></svg>
    </button>
  </div>
}

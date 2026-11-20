import { formatRelativeTime } from "../../format.ts"
import { skillSelectionLabel } from "../../skills.ts"
import SessionSidebarDivider from "../../SessionSidebarDivider.tsx"
import type { useAgentSession } from "./useAgentSession.ts"
import type { Dispatch, SetStateAction } from "react"

export function AgentSidebar({ session, sidebarWidth, setSidebarWidth, sidebarCollapsed, setSidebarCollapsed }: { session: ReturnType<typeof useAgentSession>; sidebarWidth: number; setSidebarWidth: Dispatch<SetStateAction<number>>; sidebarCollapsed: boolean; setSidebarCollapsed: Dispatch<SetStateAction<boolean>> }) {
  const { sessions, openId, runningId, createSession, selectSession, openSessionMenu } = session

  return (
    <>
      <aside id="agent-session-sidebar" className={`sidebar ${sidebarCollapsed ? "is-collapsed" : ""}`} style={{ width: sidebarWidth }}>
        <div className="brand">
          <svg className="brand-icon" aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="7" width="14" height="10" rx="2" />
            <path d="M7 7V5a3 3 0 0 1 6 0v2" />
            <circle cx="7.5" cy="12" r="1" fill="currentColor" stroke="none" />
            <circle cx="12.5" cy="12" r="1" fill="currentColor" stroke="none" />
            <path d="M10 2v2" />
          </svg>
          <div className="brand-name">
            <strong>harness</strong>
            <small>智能体</small>
          </div>
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
      <SessionSidebarDivider sidebarId="agent-session-sidebar" collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(value => !value)} onResize={setSidebarWidth}/>
    </>
  )
}

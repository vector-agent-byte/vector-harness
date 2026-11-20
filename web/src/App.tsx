import { useEffect, useState } from "react"
import "./App.css"
import "./SidebarBrand.css"
import DeepResearch from "./DeepResearch.tsx"
import SelfModeling from "./SelfModeling.tsx"
import HomePage from "./HomePage.tsx"
import { normalizeAppView, workspaceEntries } from "./appViews.ts"
import type { AppView } from "./appViews.ts"
import { AgentWorkspace } from "./features/agent/AgentWorkspace.tsx"
import { useAgentWorkspace } from "./features/agent/useAgentWorkspace.ts"

export default function App() {
  const [appView, setAppView] = useState<AppView>(() => {
    const saved = localStorage.getItem("vh-app-view")
    return normalizeAppView(saved)
  })
  const [tooltipDismissed, setTooltipDismissed] = useState(false)
  const agent = useAgentWorkspace(appView)
  const { sessions, runningId, listReady, selectSession } = agent.session
  const { workdir } = agent.files
  useEffect(() => {
    localStorage.setItem("vh-app-view", appView)
  }, [appView])

  useEffect(() => {
    const dismissTooltip = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setTooltipDismissed(true)
    }
    window.addEventListener("keydown", dismissTooltip)
    return () => window.removeEventListener("keydown", dismissTooltip)
  }, [])

  return (
    <div className="app">
      {/* Activity bar — far-left icon strip */}
      <div className="activity-bar">
        <button type="button" className={`activity-logo ${appView === "home" ? "is-active" : ""}`} title="返回首页" aria-label="返回首页" aria-current={appView === "home" ? "page" : undefined} onClick={() => setAppView("home")}>
          <svg aria-hidden="true" viewBox="0 0 48 46" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path fill="currentColor" d="M25.946 44.938c-.664.845-2.021.375-2.021-.698V33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.947 44.94z"/>
          </svg>
        </button>
        <nav className="activity-nav" aria-label="视图切换">
          {workspaceEntries.map(entry => <div className="activity-nav-entry" key={entry.id} data-tooltip-dismissed={tooltipDismissed} onMouseEnter={() => setTooltipDismissed(false)} onFocus={() => setTooltipDismissed(false)}>
            <button type="button" className={appView === entry.id ? "activity-item is-active" : "activity-item"} aria-label={entry.title} aria-describedby={`activity-description-${entry.id}`} aria-current={appView === entry.id ? "page" : undefined} onClick={() => setAppView(entry.id)}>{entry.title}</button>
            <span className="activity-tooltip" id={`activity-description-${entry.id}`} role="tooltip"><strong>{entry.title}</strong><span>{entry.description}</span></span>
          </div>)}
        </nav>
      </div>

      <div style={{ display: appView === "modeling" ? "flex" : "none", flex: 1, minWidth: 0, minHeight: 0 }}>
        <SelfModeling />
      </div>
      <div style={{ display: appView === "deepresearch" ? "flex" : "none", flex: 1, minWidth: 0, minHeight: 0 }}>
        <DeepResearch />
      </div>
      {appView === "home" ? <HomePage onNavigate={setAppView} onOpenSession={id => { setAppView("agent"); void selectSession(id) }} sessions={sessions} runningId={runningId} listReady={listReady} workdir={workdir}/> : appView === "agent" ? <AgentWorkspace agent={agent} /> : null}
    </div>
  )
}

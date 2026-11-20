import {workspaceEntries} from "./appViews.ts"
import type {WorkspaceView} from "./appViews.ts"
import type {SessionItem} from "./types.ts"
import {formatRelativeTime} from "./format.ts"
import "./HomePage.css"

function WorkspaceIcon({view}: {view: WorkspaceView}) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {view === "agent" ? <><rect x="4" y="7" width="16" height="13" rx="3"/><path d="M12 3v4M8 16h8"/><circle cx="8.5" cy="12" r=".7"/><circle cx="15.5" cy="12" r=".7"/></> :
      view === "deepresearch" ? <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5M8 10.5h5M10.5 8v5"/></> :
        <><path d="M10 2h4v4h-4zM12 6v5M4 11h16M4 11v6m8-6v6m8-6v6"/><path d="M2 17h4v4H2zM10 17h4v4h-4zM18 17h4v4h-4z"/></>}
  </svg>
}

type Props = {
  onNavigate: (view: WorkspaceView) => void;
  onOpenSession: (id: string) => void;
  sessions: SessionItem[];
  runningId: string | null;
  listReady: boolean;
  workdir: string;
}

export default function HomePage({onNavigate, onOpenSession, sessions, runningId, listReady, workdir}: Props) {
  const recent = [...sessions].sort((first, second) => second.updated_at - first.updated_at).slice(0, 4)
  return <main className="home-page">
    <header className="home-topbar"><span><strong>Vector Harness</strong><span className="home-topbar-divider">/</span>首页</span><span className="home-local-label">本地工作区</span></header>
    <div className="home-content">
      <section className="home-hero" aria-labelledby="home-title">
        <div className="home-hero-copy"><p className="home-eyebrow">YOUR INTELLIGENT WORKSPACE</p><h1 id="home-title">从一个想法，<br/>开始下一步。</h1><p className="home-intro">对话协作、深入研究、自动建模。<br/>选择适合的工作方式，让任务在这里向前推进。</p></div>
        <div className="home-journey" aria-label="工作流程：明确目标、拆解计划、执行探索、沉淀结果">
          <div className="home-journey-heading"><span className="home-journey-spark" aria-hidden="true">✦</span><span>让每一步，都通向结果</span></div>
          <ol>{[["01", "明确目标", "从你的问题出发"], ["02", "拆解计划", "把复杂任务分成步骤"], ["03", "执行探索", "通过工具与实验验证"], ["04", "沉淀结果", "留下可追溯的过程"]].map(([number, title, detail]) => <li key={number}><span className="home-journey-number">{number}</span><div><strong>{title}</strong><small>{detail}</small></div><span aria-hidden="true">↗</span></li>)}</ol>
        </div>
      </section>
      <section className="home-workspaces" aria-labelledby="home-workspaces-title">
        <div className="home-section-heading"><h2 id="home-workspaces-title">选择你的工作方式</h2><span>三个入口，一个工作区</span></div>
        <div className="home-workspace-grid">{workspaceEntries.map(entry => <button key={entry.id} type="button" className={`home-workspace-card ${entry.id}`} aria-label={`进入${entry.title}`} onClick={() => onNavigate(entry.id)}>
          <span className="home-card-heading"><span className="home-card-icon"><WorkspaceIcon view={entry.id}/></span><span className="home-card-arrow" aria-hidden="true">↗</span></span>
          <span className="home-card-brand">{entry.brand}</span><span className="home-card-title">{entry.title}</span><span className="home-card-description">{entry.description}</span>
          <span className="home-card-tags">{entry.tags.map(tag => <span key={tag}>{tag}</span>)}</span>
          <span className="home-card-action">进入工作区 <span aria-hidden="true">→</span></span>
        </button>)}</div>
      </section>
      <section className="home-recent" aria-labelledby="home-recent-title">
        <div className="home-section-heading"><h2 id="home-recent-title">最近会话</h2><button type="button" onClick={() => onNavigate("agent")}>全部会话 <span aria-hidden="true">↗</span></button></div>
        <div className="home-recent-list">{recent.length ? recent.map(session => <button type="button" className="home-recent-item" key={session.id} onClick={() => onOpenSession(session.id)}>
          <span className="home-session-icon" aria-hidden="true">↗</span><span className="home-session-title">{session.title || "未命名会话"}</span><span className={`home-session-status ${session.id === runningId ? "running" : ""}`}>{session.id === runningId ? "运行中" : formatRelativeTime(session.updated_at)}</span><span className="home-session-arrow" aria-hidden="true">→</span>
        </button>) : <div className="home-empty"><span className="home-empty-symbol" aria-hidden="true">↗</span><div><strong>{listReady ? "从第一个任务开始" : "正在加载最近会话…"}</strong><p>{listReady ? "选择上方的工作方式，之后可以在这里继续你的会话。" : "正在同步工作区中的会话记录。"}</p></div></div>}</div>
      </section>
      <footer className="home-footer"><span>你的工作，从这里继续。</span>{workdir && <span className="home-workdir" title={workdir}>工作目录 · {workdir}</span>}</footer>
    </div>
  </main>
}

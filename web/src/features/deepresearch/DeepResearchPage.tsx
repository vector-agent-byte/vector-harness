import {useState} from "react"
import type {ChatMessage} from "../../types.ts"
import {Markdown} from "../../components.tsx"
import {formatRelativeTime} from "../../format.ts"
import SessionSidebarDivider from "../../SessionSidebarDivider.tsx"
import {useDeepResearch} from "./useDeepResearch.ts"
import ResearchCreateForm from "./ResearchCreateForm.tsx"

export default function DeepResearchPage() {
const {sidebarWidth, setSidebarWidth, sidebarCollapsed, setSidebarCollapsed, openId, topicDraft, setTopicDraft, engine, setEngine, selectedTaskIndex, setSelectedTaskIndex, copied, logOpen, setLogOpen, queriesOpen, setQueriesOpen, followUpDraft, setFollowUpDraft, instructionOpen, setInstructionOpen, copiedInstruction, setCopiedInstruction, sessions, errorText, openSession, warnings, isRunning, running, starting, newTask, tasks, progress, selectedTask, taskDetail, totalEvents, statusLabel, statusClass, stopResearch, sendFollowUp, onTopicKeyDown, onFormSubmit, switchSession, copyPath, runIdleTask, removeTask} = useDeepResearch()
  return (
    <div className="research-app">
      {/* Left sidebar */}
      <aside id="research-session-sidebar" className={`research-left ${sidebarCollapsed ? "is-collapsed" : ""}`} style={{width: sidebarWidth}}>
        <div className="research-left-header">
          <div className="research-title">
            <svg
              className="research-title-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="10.5" cy="10.5" r="6.5" />
              <path d="m16 16 4.5 4.5" />
            </svg>
            <div className="research-title-name">
              <strong>deep-research</strong>
              <small>深度研究</small>
            </div>
          </div>
        </div>

        <button type="button" className="research-new-task" onClick={newTask}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
          新建研究任务
        </button>

          <div className="research-history">
            <div className="research-history-label">历史研究 · {sessions.length}</div>
            {!sessions.length && <p className="research-history-empty">每一次研究，都会留在这里。</p>}
            <ul className="research-history-list">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className={`research-history-item ${s.id === openId ? "is-open" : ""}`}
                    onClick={() => switchSession(s.id)}
                  >
                    <span className="research-history-topic">{s.topic || "无标题研究"}</span>
                    <span className={`research-history-status ${s.status}`}>
                      {s.status === "running" ? "运行中" : formatRelativeTime(s.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
      </aside>

      <SessionSidebarDivider sidebarId="research-session-sidebar" collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(value => !value)} onResize={setSidebarWidth}/>

      {/* Main content */}
      <div className="research-main">
        <header className="research-page-header">
          <div><span>深度研究</span><span>/</span><strong>{openSession ? "研究工作区" : "新建任务"}</strong></div>
          <small>本地工作区</small>
        </header>
        {errorText && <div className="research-error" role="alert">{errorText}</div>}
        {/* Top status bar */}
        {openSession && (
          <>
            <div className="research-heading">
              <div className="research-heading-row">
                <span className="research-heading-label">研究主题</span>
                <span className="research-heading-title" title={openSession.topic}>
                  {(openSession.topic.split("\n")[0] || "深度研究").slice(0, 80)}
                  {openSession.topic.replace(/\n.*/s, "").length > 80 ? "…" : ""}
                </span>
                {openSession.topic.length > 40 && (
                  <button
                    type="button"
                    className="research-instruction-toggle"
                    onClick={() => setInstructionOpen((v) => !v)}
                  >
                    {instructionOpen ? "▲" : "▼"}
                  </button>
                )}
              </div>
              {instructionOpen && (
                <div className="research-instruction-body">
                  <pre className="research-instruction-text">{openSession.topic}</pre>
                  <button
                    type="button"
                    className="research-instruction-copy"
                    onClick={() => {
                      void navigator.clipboard.writeText(openSession.topic).then(() => {
                        setCopiedInstruction(true)
                        setTimeout(() => setCopiedInstruction(false), 1500)
                      })
                    }}
                  >
                    {copiedInstruction ? "✓ 已复制" : "复制全文"}
                  </button>
                </div>
              )}
            </div>
            <div className="research-topbar">
              <span className={`research-status-label ${statusClass}`}>{statusLabel}</span>
              <span className="research-topbar-sep" />
              <span className="research-topbar-info">任务进度：{progress.done} / {progress.total}</span>
              <span className="research-topbar-sep" />
              <button
                type="button"
                className={logOpen ? "research-log-btn is-active" : "research-log-btn"}
                onClick={() => setLogOpen((v) => !v)}
              >
                阶段记录 {totalEvents} 条
              </button>
              {openSession.status === "idle" && <button className="research-log-btn" disabled={running} onClick={() => void runIdleTask()}>开始执行</button>}
              {isRunning && <button className="research-log-btn" onClick={() => void stopResearch()}>停止研究</button>}
              <button className="research-log-btn" disabled={running} onClick={() => void removeTask()}>删除任务</button>
            </div>
          </>
        )}

        {!openSession ? (
          <ResearchCreateForm topic={topicDraft} engine={engine} running={running} starting={starting}
            onTopicChange={setTopicDraft} onEngineChange={setEngine} onTopicKeyDown={onTopicKeyDown} onSubmit={onFormSubmit}/>
        ) : (
          <div className="research-content">
            {/* Center: task cards */}
            <div className="research-center">
              <div className="research-center-label">任务清单</div>
              {tasks.length === 0 && (
                <div className="research-no-tasks">
                  {isRunning ? "正在规划研究任务…" : "暂无任务数据"}
                </div>
              )}
              <div className="research-task-cards">
                  {tasks.map((task, i) => (
                    <div
                      key={task.id}
                      className={`research-task-card ${task.status} ${selectedTaskIndex === i ? "is-selected" : ""}`}
                      onClick={() => { setSelectedTaskIndex(selectedTaskIndex === i ? null : i); setQueriesOpen(false) }}
                    >
                      <div className="research-task-card-header">
                        <span className="research-task-card-title">{task.title || `任务 ${i + 1}`}</span>
                        <span className={`research-task-badge ${task.status}`}>
                          {task.status === "completed" ? "已完成" :
                           task.status === "skipped" ? "已跳过" :
                           task.status === "in_progress" ? "进行中" :
                           task.status === "error" ? "出错" :
                           task.status === "pending" ? "待执行" : "状态未知"}
                        </span>
                      </div>
                      {task.description && (
                        <div className="research-task-card-desc">{task.description}</div>
                      )}
                    </div>
                  ))}
              </div>
            </div>

            {/* Right: task detail */}
            <div className="research-right">
              {selectedTask && taskDetail ? (
                <>
                  <div className="research-detail-title">{selectedTask.title}</div>
                  {taskDetail.inferred && <p className="research-detail-inference" role="note">查询与笔记路径由执行记录推断，未经核实。</p>}
                  {selectedTask.description && (
                    <div className="research-detail-desc">{selectedTask.description}</div>
                  )}

                  {taskDetail.summary && (
                    <div className="research-detail-section research-summary-section">
                      <div className="research-detail-section-label">任务总结</div>
                      <div className="research-summary-body">
                        <Markdown text={taskDetail.summary} />
                      </div>
                    </div>
                  )}

                  {taskDetail.sources.length > 0 && (
                    <div className="research-detail-section">
                      <div className="research-detail-section-label">最新来源</div>
                      <ul className="research-sources-list">
                        {taskDetail.sources.map((src, i) => (
                          <li key={i}>
                            <a
                              className="research-source-link"
                              href={src.url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {src.title} ↗
                            </a>
                            {src.inferred && <span className="research-source-inference">推断来源 · 未经核实</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {taskDetail.notePath && (
                    <div className="research-detail-section">
                      <div className="research-detail-section-label">笔记</div>
                      <div className="research-note-row">
                        <span className="research-note-name">
                          {taskDetail.notePath.split(/[/\\]/).pop()}
                        </span>
                        <span className="research-note-tag">笔记</span>
                      </div>
                      <div className="research-path-row">
                        <span className="research-path-label">路径：</span>
                        <span className="research-path-value">{taskDetail.notePath}</span>
                        <button
                          type="button"
                          className="research-copy-btn"
                          onClick={() => copyPath(taskDetail.notePath!)}
                        >
                          {copied ? "已复制" : "复制"}
                        </button>
                      </div>
                    </div>
                  )}

                  {taskDetail.queries.length > 0 && (
                    <div className="research-detail-section">
                      <button
                        type="button"
                        className="research-detail-section-label research-queries-toggle"
                        onClick={() => setQueriesOpen((v) => !v)}
                      >
                        查询命令
                        <span className="research-queries-toggle-arrow">{queriesOpen ? "▲" : "▼"}</span>
                        <span className="research-queries-count">{taskDetail.queries.length} 条</span>
                      </button>
                      {queriesOpen && (
                        <div className="research-detail-queries">
                          {taskDetail.queries.map((q, i) => (
                            <span key={i} className="research-query-tag">{q.length > 120 ? q.slice(0, 120) + "…" : q}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {taskDetail.queries.length === 0 && taskDetail.sources.length === 0 && !taskDetail.summary && (
                    <div className="research-detail-empty">
                      {isRunning ? "任务正在执行中…" : "该任务尚无详细数据"}
                    </div>
                  )}
                </>
              ) : (
                <div className="research-detail-placeholder">
                  <div className="research-detail-placeholder-icon">📋</div>
                  <div>点击左侧任务列表或任务卡片查看详情</div>
                </div>
              )}
            </div>
          </div>
        )}

        {openSession?.report && <details className="research-report"><summary>研究报告</summary><div className="research-report-content"><Markdown text={openSession.report}/></div></details>}
        {warnings.length > 0 && <div role="alert" className="research-error">{warnings.join(" · ")}</div>}
        {/* Follow-up composer */}
        {openSession && (
          <form
            className="research-composer"
            onSubmit={(e) => { e.preventDefault(); void sendFollowUp() }}
          >
            <textarea
              className="research-followup-input"
              placeholder={isRunning ? "研究进行中，请稍候…" : "继续提问或补充研究方向，回车发送…"}
              value={followUpDraft}
              disabled={isRunning}
              rows={2}
              onChange={(e) => setFollowUpDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  void sendFollowUp()
                }
              }}
            />
            <div className="research-composer-actions">
              {isRunning ? (
                <button type="button" className="research-composer-stop" onClick={() => void stopResearch()}>
                  ■ 停止
                </button>
              ) : (
                <button
                  type="submit"
                  className="research-composer-send"
                  disabled={!followUpDraft.trim()}
                >
                  发送
                </button>
              )}
            </div>
          </form>
        )}
      </div>

      {/* Log drawer */}
      {logOpen && openSession && (
        <div className="research-log-drawer">
          <div className="research-log-header">
            <span className="research-log-title">阶段记录</span>
            <span className="research-log-count">{openSession.messages.length} 条</span>
            <button
              type="button"
              className="research-log-close"
              aria-label="关闭"
              onClick={() => setLogOpen(false)}
            >
              ✕
            </button>
          </div>
          <div className="research-log-body">
            {openSession.messages.length === 0 ? (
              <div className="research-log-empty">暂无记录</div>
            ) : (
              openSession.messages.map((msg, i) => (
                <ResearchLogEntry key={i} msg={msg} index={i} />
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ResearchLogEntry({ msg, index }: { msg: ChatMessage; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const roleLabel =
    msg.role === "user" ? "用户" :
    msg.role === "assistant" ? "助手" :
    msg.role === "tool" ? "工具" : msg.role

  const roleCls =
    msg.role === "user" ? "log-role-user" :
    msg.role === "assistant" ? "log-role-assistant" :
    msg.role === "tool" ? "log-role-tool" : "log-role-other"

  const hasToolCalls = (msg.tool_calls?.filter(c => c.name).length ?? 0) > 0
  const isLong = msg.content.length > 300
  const displayContent = isLong && !expanded ? msg.content.slice(0, 300) + "…" : msg.content

  return (
    <div className={`research-log-entry ${roleCls}${msg.is_error ? " is-error" : ""}`}>
      <div className="research-log-entry-header">
        <span className="research-log-role">{roleLabel}</span>
        {msg.is_error && <span className="research-log-err">失败</span>}
        {msg.tool_call_id && (
          <span className="research-log-tool-id" title={msg.tool_call_id}>
            #{msg.tool_call_id.slice(-6)}
          </span>
        )}
      </div>
      {msg.content && (
        <div className="research-log-content">
          <Markdown text={displayContent} />
          {isLong && (
            <button
              type="button"
              className="research-log-expand"
              onClick={() => setExpanded(v => !v)}
            >
              {expanded ? "收起" : "展开全部"}
            </button>
          )}
        </div>
      )}
      {hasToolCalls && (
        <ul className="research-log-tools">
          {msg.tool_calls?.filter(c => c.name).map((call, j) => (
            <li key={j} className="research-log-tool-item">
              <span className="research-log-tool-name">{call.name}</span>
              {call.args && (
                <span className="research-log-tool-arg">
                  {JSON.stringify(call.args).slice(0, 100)}
                  {JSON.stringify(call.args).length > 100 ? "…" : ""}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="research-log-index">#{index + 1}</div>
    </div>
  )
}

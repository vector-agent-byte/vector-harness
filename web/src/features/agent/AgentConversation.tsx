import { MODES } from "../../modes.ts"
import { skillSelectionLabel } from "../../skills.ts"
import { lastUserMessageTime, messagePresentation } from "../../reflection.ts"
import { ChildAgentCard } from "../../ChildAgentCard.tsx"
import { ChainView, Markdown, ReflectionCard, StatusNote, ThinkingBlock, TodoList, TraceView } from "../../components.tsx"
import { errorLabel, formatClock, messageTimeLabel, toolSummary, userPreview } from "../../format.ts"
import type { TodoItem } from "../../types.ts"
import type { useTranscriptNavigation } from "./useTranscriptNavigation.ts"
import type { useAgentSession } from "./useAgentSession.ts"

export function AgentConversation({ session, navigation, viewMode, setViewMode }: { session: ReturnType<typeof useAgentSession>; navigation: ReturnType<typeof useTranscriptNavigation>; viewMode: "chat" | "trace" | "chain"; setViewMode: (mode: "chat" | "trace" | "chain") => void }) {
  const { openSession, openId, errorText, listReady, sessions, runnerChain, runnerSubagents, messages, showLive, live, runningId, readingStream, lastOriginRef, liveTiming, visibleStatus, onSubmit, draft, inputLocked, setDraft, onDraftKeyDown, stopRun, selectedSkills, skillOpen, openSkillPicker, mode, chooseMode, modelName } = session
  const { bottomRef, transcriptRef, userMarks, activeUser, locatedUser, jumpToUser } = navigation

  return (
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
  )
}

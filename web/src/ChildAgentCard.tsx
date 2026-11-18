import { Markdown, ThinkingBlock } from "./components.tsx"
import { toolSummary } from "./format.ts"
import type { LiveSection } from "./types.ts"

const labels = {
  queued: "排队中", running: "运行中", complete: "已完成",
  error: "失败", max_steps: "达到步数上限", stopped: "已停止",
}

export function ChildAgentCard({ child, callId, task, active }: {
  child: LiveSection
  callId: string
  task?: string
  active: boolean
}) {
  const status = !active && (child.status === "queued" || child.status === "running") ? "stopped" : child.status
  const streaming = active && status === "running"
  return (
    <details className="child-agent-block" open>
      <summary className="child-agent-header">
        <span>子代理</span>
        <span className="child-agent-id" title={callId}>{callId}</span>
        <span className={`child-agent-status ${status ?? ""}`}>{status ? labels[status] : "历史记录"}</span>
        {streaming ? <span className="child-agent-pulse" /> : null}
      </summary>
      {task ? <div className="child-agent-task">{task}</div> : null}
      {child.thinking ? <ThinkingBlock text={child.thinking} streaming={streaming} /> : null}
      {child.text ? <Markdown text={child.text} /> : null}
      {child.tools.map((tool, index) => {
        if (!tool.name) return null
        const summary = toolSummary(tool.name, tool.args)
        return (
          <div key={`${tool.name}-${index}`} className="tool-name">
            <span className="tool-name-label">{tool.name}</span>
            {summary ? <span className="tool-name-arg">{summary.length > 80 ? summary.slice(0, 80) + "…" : summary}</span> : null}
          </div>
        )
      })}
    </details>
  )
}

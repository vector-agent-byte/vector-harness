import type { LiveSection, StreamEvent } from "./types.ts"

export function childStatus(value: unknown): LiveSection["status"] {
  switch (value) {
    case "queued": case "running": case "complete": case "error": case "max_steps": case "stopped":
      return value
    default:
      return undefined
  }
}

export function updateChildren(children: LiveSection[], event: StreamEvent): LiveSection[] {
  const isChild = event.origin === "child"
  const callId = isChild ? event.parent_tool_call_id : event.tool_call_id
  if (typeof callId !== "string" || !callId) return children
  const index = children.findIndex(child => child.toolCallId === callId)
  const isDelegate = !isChild && event.name === "delegate"
  if (index < 0 && !isChild && !isDelegate) return children
  const child: LiveSection = index < 0
    ? { toolCallId: callId, thinking: "", text: "", tools: [], status: "queued" }
    : { ...children[index] }
  if (isDelegate && event.kind === "tool_call_end") {
    const args = event.arguments as Record<string, unknown> | null
    child.task = typeof args?.task === "string" ? args.task : ""
  } else if (isDelegate && event.kind === "tool_execution_start") {
    child.status = "running"
  } else if (isChild && event.kind === "thinking_delta" && typeof event.text === "string") {
    child.thinking += event.text
  } else if (isChild && event.kind === "text_delta" && typeof event.text === "string") {
    child.text += event.text
  } else if (isChild && event.kind === "tool_call_end" && typeof event.name === "string") {
    child.tools = [...child.tools, {
      name: event.name,
      args: event.arguments && typeof event.arguments === "object" ? event.arguments as Record<string, unknown> : null,
    }]
  } else if (isChild && event.kind === "run_end") {
    child.status = childStatus(event.status) ?? "complete"
  } else if (!isChild && event.kind === "tool_result") {
    if (event.name === "error") child.status = "error"
    else if (!child.status || child.status === "queued" || child.status === "running") child.status = "complete"
  } else {
    return children
  }
  const next = [...children]
  if (index < 0) next.push(child)
  else next[index] = child
  return next
}

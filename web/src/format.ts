import type { ChatMessage, SessionItem } from "./types.ts"

export function toolSummary(name: string, args: Record<string, unknown> | null): string | null {
  if (!args) return null
  if (name === "shell" && typeof args.command === "string") return args.command
  if (typeof args.path === "string") return args.path
  if (name === "submit_verdict") return args.pass === true ? "通过" : "未通过"
  if (name === "update_todos" && Array.isArray(args.todos)) {
    const todos = args.todos as Array<Record<string, unknown>>
    const total = todos.length
    const done = todos.filter((t) => t.status === "completed").length
    return `${total} 项，${done} 完成`
  }
  const first = Object.values(args).find((v) => typeof v === "string")
  return typeof first === "string" ? first : null
}

export function formatClock(seconds: number): string {
  const date = new Date(seconds * 1000)
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function formatRelativeTime(updatedAt: number): string {
  const diffMs = Date.now() - updatedAt * 1000
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return "刚刚"
  if (diffMins < 60) return `${diffMins}分钟`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}小时`
  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays}天`
}

export function formatDuration(ms: number): string {
  const safe = Math.max(0, Math.round(ms))
  if (safe < 1000) return `${safe}毫秒`
  const totalSeconds = Math.round(safe / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes === 0) return `${seconds}秒`
  return `${minutes}分${String(seconds).padStart(2, "0")}秒`
}

export function sessionProperties(session: SessionItem, running: boolean, now: number) {
  if (session.started_at === null) {
    return { trigger: "还没有运行", duration: "还没有运行" }
  }
  const elapsed = running ? Math.max(0, now - session.started_at * 1000) : session.duration_ms
  return {
    trigger: formatClock(session.started_at),
    duration: elapsed === null ? "还在运行" : formatDuration(elapsed),
  }
}

export function viewedPath(root: string, current: string): string {
  const sep = current.includes("\\") ? "\\" : "/"
  const prefix = root.replace(/[\\/]+$/, "") + sep
  if (current.toLowerCase().startsWith(prefix.toLowerCase())) return current.slice(prefix.length)
  const name = current.split(/[\\/]/).filter(Boolean).pop()
  return name || current
}

export function errorLabel(code: string): string {
  if (code === "busy") return "正在运行"
  if (code === "not_a_directory") return "不是文件夹"
  if (code === "not_a_file") return "不是文件"
  if (code === "bad_name") return "名字不合法"
  if (code === "exists") return "已经有同名项"
  if (code === "not_found") return "没有找到"
  if (code === "bad_path") return "不能改这个位置"
  if (code === "delete_failed") return "删除没有完成"
  if (code === "rename_failed") return "重命名没有完成"
  if (code === "unknown_skill") return "没有这个技能"
  return code
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function userPreview(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim()
  if (flat.length <= 72) return flat
  return `${flat.slice(0, 72)}…`
}

export function userMessage(text: string): ChatMessage {
  return {
    role: "user",
    content: text,
    tool_calls: null,
    tool_call_id: null,
    is_error: false,
    created_at: Date.now() / 1000,
  }
}

export function messageTimeLabel(message: ChatMessage, sentAt: number | null): string | null {
  if (message.created_at === null) return null
  if (message.role !== "user" && message.role !== "assistant") return null
  const clock = formatClock(message.created_at)
  if (message.role === "assistant" && sentAt !== null) {
    return `${clock} · 耗时 ${formatDuration((message.created_at - sentAt) * 1000)}`
  }
  return clock
}

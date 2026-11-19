import type { ChatMessage } from "./types.ts"

export type ResearchTaskStatus = "pending" | "in_progress" | "completed" | "skipped" | "error"

export type ResearchTask = {
  id: string
  index: number
  title: string
  description: string
  status: ResearchTaskStatus
}

export type ResearchSource = {
  title: string
  url: string
  snippet?: string
}

export type ResearchTaskDetail = {
  queries: string[]
  notePath: string | null
  sources: ResearchSource[]
  summary: string
}

export function splitTaskContent(content: string): { title: string; description: string } {
  const newlineIdx = content.indexOf("\n")
  if (newlineIdx !== -1) {
    return {
      title: content.slice(0, newlineIdx).trim(),
      description: content.slice(newlineIdx + 1).trim(),
    }
  }
  const colonIdx = content.indexOf("：")
  if (colonIdx !== -1) {
    return {
      title: content.slice(0, colonIdx).trim(),
      description: content.slice(colonIdx + 1).trim(),
    }
  }
  const asciiColonIdx = content.indexOf(": ")
  if (asciiColonIdx !== -1 && asciiColonIdx < 30) {
    return {
      title: content.slice(0, asciiColonIdx).trim(),
      description: content.slice(asciiColonIdx + 2).trim(),
    }
  }
  return { title: content.trim(), description: "" }
}

function mapTodoStatus(status: string): ResearchTaskStatus {
  if (status === "completed") return "completed"
  if (status === "in_progress") return "in_progress"
  if (status === "skipped") return "skipped"
  if (status === "error") return "error"
  return "pending"
}

export function extractResearchTasks(messages: ChatMessage[]): ResearchTask[] {
  let lastTodos: Array<{ id?: string; content: string; status: string }> | null = null
  for (const msg of messages) {
    for (const call of msg.tool_calls ?? []) {
      if (call.name === "update_todos" && Array.isArray(call.args?.todos)) {
        lastTodos = call.args!.todos as Array<{ id?: string; content: string; status: string }>
      }
    }
  }
  if (!lastTodos) return []
  return lastTodos.map((todo, i) => {
    const { title, description } = splitTaskContent(todo.content)
    return {
      id: todo.id ?? `task-${i}`,
      index: i,
      title,
      description,
      status: mapTodoStatus(todo.status),
    }
  })
}

export function parseSources(content: string): ResearchSource[] {
  const sources: ResearchSource[] = []
  const mdLinkRe = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g
  let match: RegExpExecArray | null
  while ((match = mdLinkRe.exec(content)) !== null) {
    sources.push({ title: match[1], url: match[2] })
  }
  if (sources.length > 0) return sources
  const urlRe = /https?:\/\/[^\s<>"')\]]+/g
  while ((match = urlRe.exec(content)) !== null) {
    const url = match[0].replace(/[.,;:!?]+$/, "")
    if (!sources.some((s) => s.url === url)) {
      sources.push({ title: url, url })
    }
  }
  return sources
}

export function extractTaskDetail(taskIndex: number, messages: ChatMessage[]): ResearchTaskDetail {
  const childCalls: Array<{ queries: string[]; notePath: string | null; summary: string; callId: string }> = []
  for (const msg of messages) {
    for (const call of msg.tool_calls ?? []) {
      if (call.child) {
        const queries: string[] = []
        let notePath: string | null = null
        for (const tool of call.child.tools) {
          if (!tool.name) continue
          if (tool.name === "shell" && typeof tool.args?.command === "string") {
            const cmd = tool.args.command as string
            if (cmd.includes("search") || cmd.includes("curl") || cmd.includes("wget")) {
              queries.push(cmd)
            }
          }
          if ((tool.name === "write_file" || tool.name === "edit" || tool.name === "write") && typeof tool.args?.path === "string") {
            const p = tool.args.path as string
            if (p.includes("note") || p.endsWith(".md")) {
              notePath = p
            }
          }
        }
        // child.text comes from streamed text_delta events; if empty, the tool
        // result message holds the same final text from the child loop
        let summary = call.child.text
        if (!summary) {
          for (const m of messages) {
            if (m.role === "tool" && m.tool_call_id === call.id && m.content) {
              summary = m.content
              break
            }
          }
        }
        childCalls.push({ queries, notePath, summary, callId: call.id })
      }
    }
  }

  const entry = childCalls[taskIndex]
  if (!entry) {
    return { queries: [], notePath: null, sources: [], summary: "" }
  }

  const sources: ResearchSource[] = []
  for (const msg of messages) {
    if (msg.role === "tool" && msg.tool_call_id === entry.callId) {
      sources.push(...parseSources(msg.content))
    }
  }

  if (sources.length === 0 && entry.summary) {
    sources.push(...parseSources(entry.summary))
  }

  return {
    queries: entry.queries,
    notePath: entry.notePath,
    sources,
    summary: entry.summary,
  }
}

export function extractResearchTopic(messages: ChatMessage[]): string {
  for (const msg of messages) {
    if (msg.role === "user" && msg.content.trim()) {
      const content = msg.content.trim()
      const topicMatch = content.match(/主题[：:]\s*(.+?)(?:\n|$)/)
      if (topicMatch) return topicMatch[1].trim()
      return content.split("\n")[0].trim()
    }
  }
  return ""
}

export function getResearchProgress(tasks: ResearchTask[]): { done: number; total: number } {
  const done = tasks.filter((t) => t.status === "completed" || t.status === "skipped").length
  return { done, total: tasks.length }
}

function mapChildStatus(raw: string | undefined): ResearchTaskStatus {
  if (raw === "complete") return "completed"
  if (raw === "error" || raw === "max_steps") return "error"
  if (raw === "running") return "in_progress"
  if (raw === "stopped") return "skipped"
  if (raw === "queued") return "pending"
  return "completed"
}

export function extractResearchTasksFromDelegates(messages: ChatMessage[]): ResearchTask[] {
  const tasks: ResearchTask[] = []
  for (const msg of messages) {
    for (const call of msg.tool_calls ?? []) {
      if (!call.child) continue
      const taskText =
        typeof call.args?.task === "string" ? call.args.task :
        call.child.text.split("\n")[0].trim() || `子任务 ${tasks.length + 1}`
      const { title, description } = splitTaskContent(taskText)
      const status = mapChildStatus(call.child.status)
      tasks.push({
        id: call.id || `delegate-${tasks.length}`,
        index: tasks.length,
        title,
        description,
        status,
      })
    }
  }
  return tasks
}

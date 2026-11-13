export type SessionItem = {
  id: string
  title: string
  updated_at: number
  skill: string | null
  started_at: number | null
  duration_ms: number | null
}

export type SkillItem = {
  name: string
  description: string
}

export type DirEntry = {
  name: string
  path: string
}

export type DirListing = {
  path: string
  parent: string | null
  dirs: DirEntry[]
  files: DirEntry[]
}

export type ToolCall = {
  id: string
  name: string
  args: Record<string, unknown> | null
}

export type ChatMessage = {
  role: string
  content: string
  tool_calls: ToolCall[] | null
  tool_call_id: string | null
  is_error: boolean
  created_at: number | null
}

export type LiveTool = {
  name: string
  args: Record<string, unknown> | null
}

export type LiveSection = {
  thinking: string
  text: string
  tools: LiveTool[]
}

export type LiveTurn = {
  thinking: string
  text: string
  tools: LiveTool[]
  children: LiveSection[]
}

export type SessionList = {
  sessions: SessionItem[]
  running_id: string | null
  model: string
}

export type StreamEvent = {
  kind?: unknown
  text?: unknown
  name?: unknown
  status?: unknown
  arguments?: unknown
  tool_call_id?: unknown
  origin?: unknown
}

export type RunNote = {
  id: string
  status: string
}

export type TodoItem = { id?: string; content: string; status: string }

export type StatusKind = "warn" | "error" | "neutral"

export type EntryKind = "file" | "dir"

export type EntryMenu = {
  kind: EntryKind
  name: string
  path: string
  x: number
  y: number
}

export type FilePreview = {
  name: string
  path: string
  kind: "text" | "image" | "too_large" | "unsupported"
  text: string
}

export type NamedPath = {
  name: string
  path: string
}

export type SessionMenu = {
  id: string
  x: number
  y: number
}

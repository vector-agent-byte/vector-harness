import type {
  ChatMessage,
  DirEntry,
  DirListing,
  SessionList,
  SessionItem,
  SkillItem,
  StreamEvent,
  ToolCall,
} from "./types.ts"

export function parseSessionList(value: unknown): SessionList | null {
  if (!value || typeof value !== "object") return null
  const record = value as Record<string, unknown>
  if (!Array.isArray(record.sessions)) return null
  if (record.running_id !== null && typeof record.running_id !== "string") return null
  const sessions: SessionItem[] = []
  for (const item of record.sessions) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.id !== "string" || typeof row.title !== "string") continue
    sessions.push({
      id: row.id,
      title: row.title,
      updated_at: typeof row.updated_at === "number" ? row.updated_at : 0,
      skill: typeof row.skill === "string" && row.skill !== "" ? row.skill : null,
      started_at: typeof row.started_at === "number" ? row.started_at : null,
      duration_ms: typeof row.duration_ms === "number" ? row.duration_ms : null,
    })
  }
  const runningId = record.running_id
  return {
    sessions,
    running_id: typeof runningId === "string" ? runningId : null,
    model: typeof record.model === "string" ? record.model : "",
  }
}

export function normalizeTools(value: unknown): ToolCall[] | null {
  if (value == null) return null
  if (!Array.isArray(value)) return null
  const tools: ToolCall[] = []
  for (const item of value) {
    if (!item || typeof item !== "object") continue
    const record = item as Record<string, unknown>
    tools.push({
      id: typeof record.id === "string" ? record.id : "",
      name: typeof record.name === "string" ? record.name : "",
      args:
        record.arguments && typeof record.arguments === "object"
          ? (record.arguments as Record<string, unknown>)
          : null,
    })
  }
  return tools
}

export function normalizeMessages(value: unknown): ChatMessage[] {
  if (!Array.isArray(value)) return []
  const messages: ChatMessage[] = []
  for (const item of value) {
    if (!item || typeof item !== "object") continue
    const record = item as Record<string, unknown>
    messages.push({
      role: typeof record.role === "string" ? record.role : "",
      content: typeof record.content === "string" ? record.content : "",
      tool_calls: normalizeTools(record.tool_calls),
      tool_call_id: typeof record.tool_call_id === "string" ? record.tool_call_id : null,
      is_error: record.is_error === true,
      created_at: typeof record.created_at === "number" ? record.created_at : null,
    })
  }
  return messages
}

export async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: unknown }
    if (typeof body.error === "string") return body.error
  } catch {
    // A 4xx without JSON still needs a visible error string.
  }
  return "bad_request"
}

export function parseEvent(block: string): StreamEvent | null {
  const line = block
    .split("\n")
    .map((item) => item.trim())
    .find((item) => item.startsWith("data:"))
  if (!line) return null
  try {
    const value = JSON.parse(line.slice(5).trim()) as unknown
    if (!value || typeof value !== "object") return null
    return value as StreamEvent
  } catch {
    return null
  }
}

export async function readEventStream(
  response: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<{ completed: boolean; status: string | null }> {
  const reader = response.body?.getReader()
  if (!reader) return { completed: false, status: null }
  const decoder = new TextDecoder()
  let buffer = ""
  let completed = false
  let status: string | null = null

  const applyBlock = (block: string) => {
    const event = parseEvent(block)
    if (!event || typeof event.kind !== "string") return
    onEvent(event)
    if (event.kind === "run_result") {
      completed = true
      status = typeof event.status === "string" ? event.status : ""
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split("\n\n")
      buffer = parts.pop() ?? ""
      for (const part of parts) applyBlock(part)
    }
    buffer += decoder.decode()
    if (buffer.trim()) applyBlock(buffer)
  } catch {
    // Dropped before run_result: the caller polls instead of resending.
  }
  return { completed, status }
}

export function parseSkills(value: unknown): SkillItem[] {
  if (!value || typeof value !== "object") return []
  const record = value as Record<string, unknown>
  if (!Array.isArray(record.skills)) return []
  const skills: SkillItem[] = []
  for (const item of record.skills) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.name !== "string" || typeof row.description !== "string") continue
    skills.push({ name: row.name, description: row.description })
  }
  return skills
}

export function parseEntries(value: unknown): DirEntry[] {
  if (!Array.isArray(value)) return []
  const entries: DirEntry[] = []
  for (const item of value) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.name !== "string" || typeof row.path !== "string") continue
    entries.push({ name: row.name, path: row.path })
  }
  return entries
}

export function parseDirs(value: unknown): DirListing | null {
  if (!value || typeof value !== "object") return null
  const record = value as Record<string, unknown>
  if (typeof record.path !== "string" || !Array.isArray(record.dirs)) return null
  return {
    path: record.path,
    parent: typeof record.parent === "string" ? record.parent : null,
    dirs: parseEntries(record.dirs),
    files: parseEntries(record.files),
  }
}

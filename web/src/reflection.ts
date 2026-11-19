import type { ChatMessage } from "./types.ts"

export type Reflection = { pass: boolean; text: string }

export function parseReflection(content: string): Reflection | null {
  const verdict = content.match(/^\[(?:反思|Reflection)\]\s*(通过|未通过)\s*[—-]\s*(.*)$/s)
  if (verdict) return { pass: verdict[1] === "通过", text: verdict[2].trim() }
  const feedback = content.match(/^(?:反思意见：|Reflection:)\s*(.*)$/s)
  return feedback ? { pass: false, text: feedback[1].trim() } : null
}

export function messagePresentation(message: ChatMessage) {
  const reflection = message.role === "user" || message.role === "assistant"
    ? parseReflection(message.content) : null
  return {
    role: reflection ? "assistant" : message.role,
    isUser: message.role === "user" && reflection === null,
    reflection,
  }
}

export function reflectionInitiallyOpen(text: string): boolean {
  return text.length <= 240 && text.split(/\r?\n/).length <= 4
}

export function lastUserMessageTime(messages: ChatMessage[]): number | null {
  return messages.findLast(message => messagePresentation(message).isUser && message.created_at !== null)?.created_at ?? null
}

export function reflectionPreview(text: string): string {
  const flattened = text.replace(/\s+/g, " ").trim()
  return flattened.length > 120 ? flattened.slice(0, 120) + "…" : flattened
}

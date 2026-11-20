import type { TaskBase } from "../tasks/api.ts"

export type ResearchTaskStatus = "pending" | "in_progress" | "completed" | "skipped" | "error" | "unknown"
export type ResearchTask = {id: string; index: number; title: string; description: string; status: ResearchTaskStatus}
export type ResearchSource = {title: string; url: string; inferred?: boolean}
export type ResearchTaskDetail = {queries: string[]; notePath: string | null; sources: ResearchSource[]; summary: string; inferred?: boolean}
export type ResearchSnapshot = TaskBase & {
  kind: "deepresearch"
  config: {topic: string; engine: string}
  topic: string
  tasks?: ResearchTask[]
  details?: Record<string, ResearchTaskDetail>
  report?: string
  progress?: {done: number; total: number}
}

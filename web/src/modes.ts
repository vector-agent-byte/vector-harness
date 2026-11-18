export const MODES = [
  { id: "react",     label: "ReAct" },
  { id: "plan",      label: "PlanAndSolve" },
  { id: "reflect",   label: "Reflection" },
  { id: "subagents", label: "SubAgents" },
] as const

export type ModeId = (typeof MODES)[number]["id"]

export function normalizeMode(value: unknown): ModeId {
  return MODES.find(mode => mode.id === value)?.id ?? "react"
}

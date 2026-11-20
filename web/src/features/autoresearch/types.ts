import type { TaskBase } from "../tasks/api.ts"
import type { Experiment, ModelConfig } from "./config.ts"

export type ModelSnapshot = TaskBase & {
  kind: "autoresearch"
  config: ModelConfig
  experiments?: Experiment[]
  baselineId?: number | null
  bestId?: number | null
  metricDirection?: "minimize" | "maximize"
  improvement?: number | null
  output?: string
}
export type ModelField = {
  type: "string" | "number" | "integer" | "array"
  required?: boolean
  requiredWhen?: Partial<ModelConfig>
  enum?: string[]
  minimum?: number
  maximum?: number
  maxLength?: number
  items?: {type: "string"; enum?: string[]}
}
export type ModelOptionKey = "task" | "metric" | "split" | "strategy" | "algorithms"
export type ModelOptions = {
  defaults: ModelConfig
  fields: Partial<Record<keyof ModelConfig, ModelField>> & {
    metric?: ModelField & {enumByTask?: Record<string, string[]>}
    threshold?: ModelField & {maximumByMetric?: Record<string, number>; defaultByTask?: Record<string, number>}
  }
  enums: Record<ModelOptionKey, string[]> & {metricByTask?: Record<string, string[]>}
}

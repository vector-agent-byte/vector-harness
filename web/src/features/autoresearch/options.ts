import type {ModelConfig} from "./config.ts"
import type {ModelOptionKey, ModelOptions} from "./types.ts"

export function fieldChoices(options: ModelOptions | null, key: ModelOptionKey, config: ModelConfig): string[] {
    if (!options) return []
    if (key === "metric") return options.fields.metric?.enumByTask?.[config.task] ?? options.enums.metricByTask?.[config.task] ?? options.fields.metric?.enum ?? options.enums.metric
    if (key === "algorithms") return options.fields.algorithms?.items?.enum ?? options.enums.algorithms
    return options.fields[key]?.enum ?? options.enums[key]
}

export function fieldInputProps(options: ModelOptions | null, key: keyof ModelConfig, config: ModelConfig) {
    const field = options?.fields[key]
    const conditions = field?.requiredWhen
    return {
        required: field?.required === true || !!conditions && Object.entries(conditions).every(([name, value]) => config[name as keyof ModelConfig] === value),
        min: field?.minimum,
        max: key === "threshold" ? options?.fields.threshold?.maximumByMetric?.[config.metric] ?? field?.maximum : field?.maximum,
        step: field?.type === "integer" ? 1 : field?.type === "number" ? "any" : undefined,
        maxLength: field?.maxLength,
    }
}

export function taskDraft(config: ModelConfig, task: string, options: ModelOptions): ModelConfig {
    return {
        ...config,
        task,
        metric: fieldChoices(options, "metric", {...config, task})[0] ?? options.defaults.metric,
        threshold: options.fields.threshold?.defaultByTask?.[task] ?? options.defaults.threshold,
    }
}

export function applyServerDefaults(config: ModelConfig, defaults: ModelConfig, edited: ReadonlySet<keyof ModelConfig>): ModelConfig {
    return {...defaults, ...Object.fromEntries([...edited].map(key => [key, config[key]]))}
}

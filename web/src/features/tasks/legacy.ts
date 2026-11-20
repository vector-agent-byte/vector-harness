import {jsonBody, requestJson} from "./api.ts"
import type {TaskKind, Transport} from "./api.ts"

type Storage = Pick<globalThis.Storage, "getItem" | "setItem">
export type LegacyResult = { raw: string; errors: string[] }
const keys = {deepresearch: ["vh-research-ids", "vh-research-meta"], autoresearch: ["vh-modeling-sessions-v1"]}
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value)
const pending = new WeakMap<Storage, Map<TaskKind, Promise<LegacyResult>>>()

export function importLegacy(kind: TaskKind, storage: Storage, transport: Transport = fetch): Promise<LegacyResult> {
    let imports = pending.get(storage)
    if (!imports) {
        imports = new Map();
        pending.set(storage, imports)
    }
    const existing = imports.get(kind)
    if (existing) return existing
    const request = migrateLegacy(kind, storage, transport).finally(() => imports.delete(kind))
    imports.set(kind, request)
    return request
}

async function migrateLegacy(kind: TaskKind, storage: Storage, transport: Transport): Promise<LegacyResult> {
    const original: Record<string, string | null> = {}
    let raw = ""
    try {
        for (const key of keys[kind]) {
            original[key] = storage.getItem(key)
            raw = JSON.stringify(original, null, 2)
        }
        const savedValue: unknown = JSON.parse(original[keys[kind][0]] ?? "[]")
        const metadata: unknown = kind === "deepresearch" ? JSON.parse(original[keys[kind][1]] ?? "{}") : {}
        if (!Array.isArray(savedValue) || !record(metadata)) return {raw, errors: ["旧记录格式无效，请导出备份。"]}
        const saved = kind === "deepresearch" ? [...new Set([...savedValue, ...Object.keys(metadata)])] : savedValue
        if (!saved.length) return {raw: "", errors: []}
        const tasks = saved.flatMap<{ id: string; kind: TaskKind; config: unknown }>(item => {
            if (kind === "deepresearch" && typeof item === "string") {
                const meta = record(metadata[item]) ? metadata[item] : {}
                return [{
                    id: item,
                    kind,
                    config: {topic: meta.topic, ...(typeof meta.engine === "string" ? {engine: meta.engine} : {})}
                }]
            }
            if (kind === "autoresearch" && record(item) && typeof item.id === "string") return [{
                id: item.id,
                kind,
                config: item.config
            }]
            return []
        })
        const {results} = await requestJson<{
            results: { id: string; status: string; error?: string }[]
        }>("/api/tasks/import-legacy", jsonBody({tasks}), transport)
        const successful = new Set(tasks.filter(task => {
            const matches = results.filter(result => result.id === task.id)
            return matches.length > 0 && matches.every(result => result.status === "imported" || result.status === "already_imported")
        }).map(task => task.id))
        for (const key of keys[kind]) if (storage.getItem(key) !== original[key]) return {
            raw,
            errors: ["旧记录已变化，保留原记录以便重试。"]
        }
        const remaining = saved.filter(item => !successful.has(typeof item === "string" ? item : record(item) && typeof item.id === "string" ? item.id : ""))
        if (successful.size) {
            if (kind === "deepresearch") {
                const retained = Object.fromEntries(Object.entries(metadata).filter(([id]) => !successful.has(id)))
                storage.setItem(keys[kind][1], JSON.stringify(retained))
            }
            storage.setItem(keys[kind][0], JSON.stringify(remaining))
        }
        return {
            raw: remaining.length ? raw : "",
            errors: remaining.length ? results.filter(result => !successful.has(result.id)).map(result => `${result.id}: ${result.error ?? result.status}`).concat("部分旧记录未迁移；原始数据仍保留，可导出备份。") : []
        }
    } catch (error) {
        return {raw, errors: [String(error)]}
    }
}

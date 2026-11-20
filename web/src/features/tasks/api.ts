import {normalizeMessages, normalizeWarnings, readError, readEventStream} from "../../api.ts"
import type {ChatMessage, StreamEvent} from "../../types.ts"

export type TaskKind = "deepresearch" | "autoresearch"
export type TaskStatus = "idle" | "running" | "completed" | "stopped" | "error" | "interrupted"
export type TaskBase = {
    id: string;
    kind: TaskKind;
    config: object;
    status: TaskStatus;
    updated_at: number;
    revision?: number
}
export type TaskDetail<Task> = { task: Task; messages: ChatMessage[]; warnings: string[] }
export type TaskCreate<Task extends TaskBase> = Task extends {kind: "deepresearch"}
    ? {topic: string; engine: "advanced" | "standard"}
    : Task extends {kind: "autoresearch"}
        ? {config: Task["config"]; parentSessionId?: string; parentExperimentId?: number}
        : {topic: string; engine: "advanced" | "standard"} | {config: object; parentSessionId?: string; parentExperimentId?: number}
export type Transport = typeof fetch

export class TaskHttpError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "TaskHttpError"
        this.status = status
    }
}

async function taskError(response: Response): Promise<string> {
    try {
        const body = await response.clone().json() as { message?: unknown }
        if (typeof body.message === "string" && body.message.trim()) return body.message
    } catch {
    }
    return readError(response)
}

export async function requestJson<Value>(url: string, init?: RequestInit, transport: Transport = fetch): Promise<Value> {
    const response = await transport(url, {cache: "no-store", ...init})
    if (!response.ok) throw new TaskHttpError(response.status, await taskError(response))
    return response.json() as Promise<Value>
}

export const jsonBody = (body: unknown): RequestInit => ({
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
})

export function taskApi<Task extends TaskBase = TaskBase>(kind: TaskKind, transport: Transport = fetch) {
    const base = `/api/${kind}/tasks`
    const path = (id: string) => `${base}/${encodeURIComponent(id)}`
    const stream = async (url: string, body: unknown, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) => {
        const response = await transport(url, {...jsonBody(body), signal})
        if (!response.ok) throw new TaskHttpError(response.status, await taskError(response))
        return readEventStream(response, onEvent)
    }
    return {
        list: () => requestJson<{ tasks: Task[]; running_id: string | null }>(base, undefined, transport),
        create: (body: TaskCreate<Task>) => requestJson<Task>(base, jsonBody(body), transport),
        detail: async (id: string): Promise<TaskDetail<Task>> => {
            const result = await requestJson<{
                task: Task;
                messages: unknown;
                warnings: unknown
            }>(path(id), undefined, transport)
            return {
                task: result.task,
                messages: normalizeMessages(result.messages),
                warnings: normalizeWarnings(result.warnings)
            }
        },
        run: (id: string, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) => stream(`${path(id)}/run`, {}, onEvent, signal),
        message: (id: string, text: string, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) => stream(`${path(id)}/messages`, {text}, onEvent, signal),
        stop: (id: string) => requestJson(`${path(id)}/stop`, jsonBody({}), transport),
        remove: (id: string) => requestJson(path(id), {method: "DELETE"}, transport),
    }
}

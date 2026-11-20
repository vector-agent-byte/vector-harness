import type {ChatMessage, StreamEvent} from "../../types.ts"

export type ModelLog = {kind: string; label: string; content: string; source: string; toolCallId?: string; toolName?: string; createdAt?: number | null}

export function describeModelLog(entry: ModelLog) {
    const content = entry.content
    let preview = content
    const todos: {content: string; status: string}[] = []
    if (entry.kind === "tool_call_end") {
        try {
            const args: unknown = JSON.parse(content)
            if (args && typeof args === "object" && !Array.isArray(args)) {
                const record = args as Record<string, unknown>
                if (Array.isArray(record.todos)) {
                    for (const item of record.todos) {
                        if (item && typeof item === "object" && typeof item.content === "string") {
                            todos.push({content: item.content, status: typeof item.status === "string" ? item.status : "pending"})
                        }
                    }
                }
                if (todos.length) {
                    const completed = todos.filter(todo => todo.status === "completed").length
                    const current = todos.find(todo => todo.status === "in_progress")
                    preview = `已完成 ${completed}/${todos.length} 项${current ? ` · 进行中：${current.content}` : ""}`
                } else {
                    const summary = record.command ?? record.task ?? record.path
                    if (typeof summary === "string") preview = summary
                }
            }
        } catch {
            preview = content
        }
    }
    preview = preview.replace(/\s+/g, " ").trim()
    if (preview.length > 160) preview = `${preview.slice(0, 159)}…`
    return {preview, content, todos}
}

export function appendModelLog(logs: ModelLog[], event: StreamEvent, createdAt: number | null = Date.now()): ModelLog[] {
    const source = event.origin === "child" ? `child:${String(event.parent_tool_call_id ?? "")}` : "main"
    const prefix = event.origin === "child" ? "子任务 · " : ""
    const toolCallId = typeof event.tool_call_id === "string" ? event.tool_call_id : ""
    const name = typeof event.name === "string" && event.name ? event.name :
        (toolCallId ? logs.findLast(entry => entry.toolCallId === toolCallId && entry.source === source)?.toolName : undefined) ?? "工具"
    const kind = typeof event.kind === "string" ? event.kind : ""
    let label: string
    let content: string
    if (kind === "thinking_delta" || kind === "text_delta") {
        if (typeof event.text !== "string" || !event.text) return logs
        const last = logs.at(-1)
        if (last?.kind === kind && last.source === source) {
            return [...logs.slice(0, -1), {...last, content: last.content + event.text}]
        }
        if (!event.text.trim()) return logs
        label = kind === "thinking_delta" ? "思考" : "智能体输出"
        content = event.text
    } else if (kind === "tool_call_end") {
        label = `调用工具 · ${name}`
        content = event.arguments ? JSON.stringify(event.arguments, null, 2) : ""
    } else if (kind === "tool_execution_start") {
        label = `执行中 · ${name}`
        content = ""
    } else if (kind === "tool_result") {
        label = name === "error" ? "工具执行失败" : `执行结果 · ${name}`
        content = typeof event.text === "string" ? event.text : ""
    } else {
        return logs
    }
    return [...logs, {kind, label: prefix + label, content, source, createdAt, ...(toolCallId ? {toolCallId, toolName: name} : {})}]
}

export function modelLogsFromMessages(messages: ChatMessage[]): ModelLog[] {
    let logs: ModelLog[] = []
    const tools = new Map<string, string>()
    for (const message of messages) {
        const createdAt = typeof message.created_at === "number" && Number.isFinite(message.created_at) ? message.created_at * 1000 : null
        if (message.role === "assistant") {
            logs = appendModelLog(logs, {kind: "text_delta", text: message.content}, createdAt)
            for (const tool of message.tool_calls ?? []) {
                tools.set(tool.id, tool.name)
                logs = appendModelLog(logs, {kind: "tool_call_end", name: tool.name, arguments: tool.args}, createdAt)
                if (tool.child) {
                    logs = appendModelLog(logs, {kind: "thinking_delta", origin: "child", parent_tool_call_id: tool.id, text: tool.child.thinking}, null)
                    logs = appendModelLog(logs, {kind: "text_delta", origin: "child", parent_tool_call_id: tool.id, text: tool.child.text}, null)
                }
            }
        } else if (message.role === "tool") {
            const name = tools.get(message.tool_call_id ?? "") ?? "工具"
            logs.push({kind: "tool_result", label: `${name} · ${message.is_error ? "执行失败" : "执行结果"}`, content: message.content, source: "main", createdAt})
        }
    }
    return logs
}

import {Markdown} from "./components.tsx"
import {describeModelLog} from "./modeling.ts"
import type {ModelLog} from "./modeling.ts"

const todoLabels: Record<string, string> = {pending: "待开始", in_progress: "进行中", completed: "已完成"}
const logTimeFormat = new Intl.DateTimeFormat("zh-CN", {year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"})

export default function ModelExecutionLogs({logs}: {logs: ModelLog[]}) {
    return <div className="model-execution-logs">
        <div className="model-log-toolbar"><span>最新在上</span><span>共 {logs.length} 条日志 · 点击展开详情</span></div>
        <div className="model-log-list" role="log" aria-label="任务执行日志">
            {logs.map((entry, index) => {
                const display = describeModelLog(entry)
                const triggeredAt = typeof entry.createdAt === "number" ? new Date(entry.createdAt) : null
                const hasTime = triggeredAt !== null && Number.isFinite(triggeredAt.getTime())
                const failed = entry.label.includes("失败")
                const tone = failed ? "error" : entry.kind === "thinking_delta" ? "thinking" : entry.kind === "tool_result" ? "result" : "activity"
                const icon = failed ? "!" : entry.kind === "thinking_delta" ? "✦" : entry.kind === "tool_result" ? "↳" : entry.kind === "text_delta" ? "≡" : ">_"
                const heading = <>
                    <span className={`model-log-icon ${tone}`} aria-hidden="true">{icon}</span>
                    <span className="model-log-summary-text">
                        <span className="model-log-title"><strong>{entry.label}</strong>{index === logs.length - 1 && <span className="model-log-latest">最新</span>}
                            <span className="model-log-meta">{hasTime ? <time dateTime={triggeredAt.toISOString()} title="日志时间（本地时间）">{logTimeFormat.format(triggeredAt)}</time> : <span>时间未记录</span>}<span className="model-log-number">#{index + 1}</span></span>
                        </span>
                        {display.preview && <span className="model-log-preview">{display.preview}</span>}
                    </span>
                </>
                if (!display.content.trim()) return <div className="model-log-entry model-log-summary" key={index}>{heading}</div>
                return <details className={`model-log-entry ${failed ? "is-error" : ""}`} key={index}>
                    <summary className="model-log-summary">{heading}<span className="model-log-toggle" aria-hidden="true"/></summary>
                    <div className="model-log-body">
                        {display.todos.length ? <>
                            <ul className="model-log-todos">{display.todos.map((todo, todoIndex) => <li key={todoIndex}>
                                <span className={`model-log-todo-state ${Object.hasOwn(todoLabels, todo.status) ? todo.status : "pending"}`}>{todoLabels[todo.status] ?? "待开始"}</span>
                                <span>{todo.content}</span>
                            </li>)}</ul>
                            <details className="model-log-raw"><summary>查看原始参数</summary><pre>{display.content}</pre></details>
                        </> : entry.kind === "text_delta" ? <Markdown text={display.content}/> : <pre>{display.content}</pre>}
                    </div>
                </details>
            }).reverse()}
        </div>
    </div>
}

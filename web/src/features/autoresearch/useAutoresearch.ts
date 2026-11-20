import {useEffect, useRef, useState} from "react"
import type {FormEvent} from "react"
import {useTasks} from "../tasks/useTasks.ts"
import {requestJson} from "../tasks/api.ts"
import type {TaskStatus} from "../tasks/api.ts"
import {defaultModelConfig} from "./config.ts"
import type {ModelConfig, Experiment} from "./config.ts"
import type {ModelSnapshot, ModelOptions} from "./types.ts"
import {demoConfig, demoSnapshot} from "./demo.ts"
import {appendModelLog, modelLogsFromMessages} from "./logs.ts"
import type {ModelLog} from "./logs.ts"
import {applyServerDefaults, fieldChoices, fieldInputProps, taskDraft} from "./options.ts"

export const statusLabels: Record<TaskStatus, string> = {
    idle: "等待开始",
    running: "探索中",
    completed: "执行结束",
    stopped: "已停止",
    error: "执行失败",
    interrupted: "执行中断"
}

export function useAutoresearch() {

    const [sidebarWidth, setSidebarWidth] = useState<number | undefined>(undefined)
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
    const [openId, setOpenId] = useState<string | null>(null)
    const [config, setConfig] = useState<ModelConfig>({...defaultModelConfig})
    const [options, setOptions] = useState<ModelOptions | null>(null)
    const optionsReady = options !== null
    const edited = useRef(new Set<keyof ModelConfig>())
    const [tab, setTab] = useState("experiments")
    const [selectedId, setSelectedId] = useState(0)
    const [filter, setFilter] = useState("all")
    const [detailTab, setDetailTab] = useState("plan")
    const [advanced, setAdvanced] = useState(false)
    const [search, setSearch] = useState("")
    const [notice, setNotice] = useState("")
    const [starting, setStarting] = useState(false)
    const [stopping, setStopping] = useState(false)
    const [parent, setParent] = useState<(Experiment & { sessionId: string }) | undefined>()
    const launchLock = useRef(false)
    const [liveLogs, setLiveLogs] = useState<Record<string, ModelLog[]>>({})
    const controller = useTasks<ModelSnapshot>("autoresearch", openId)
    const {tasks: sessions, error, setError} = controller
    useEffect(() => {
        if (controller.loaded && openId && openId !== "demo" && !sessions.some(task => task.id === openId)) setOpenId(null)
    }, [controller.loaded, openId, sessions])
    const demo = openId === "demo"
    const task = sessions.find(item => item.id === openId)
    const detail = openId ? controller.details[openId] : undefined
    const warnings = detail?.warnings ?? []
    const session = task ? {
        ...task,
        output: task.output ?? "",
        logs: controller.streamingId === task.id ? liveLogs[task.id] ?? modelLogsFromMessages(detail?.messages ?? []) : modelLogsFromMessages(detail?.messages ?? [])
    } : undefined
    const currentConfig = demo ? demoConfig : session?.config ?? config
    const snapshot: Partial<ModelSnapshot> = demo ? demoSnapshot : session ?? {}
    const experiments = snapshot.experiments ?? []
    const best = experiments.find(item => item.id === snapshot.bestId)
    const selected = experiments.find(item => item.id === selectedId) ?? experiments[0]
    const running = sessions.find(item => item.status === "running" || item.id === controller.streamingId || item.id === controller.runningId)
    const busy = starting || !!running || !!controller.runningId || !!controller.streamingId
    const viewing = demo || !!session
    const improvement = snapshot.improvement ?? null
    const metricDirection = snapshot.metricDirection
    const filtered = experiments.filter(item => filter === "all" || (filter === "best" ? item.isBest === true || item.id === snapshot.bestId : item.improved === true))
    useEffect(() => {
        let active = true
        void requestJson<ModelOptions>("/api/autoresearch/options").then(options => {
            if (!active) return
            setOptions(options)
            setConfig(previous => applyServerDefaults(previous, options.defaults, edited.current))
        }).catch(reason => {
            if (active) setError(String(reason))
        })
        return () => {
            active = false
        }
    }, [setError])

    function change<Key extends keyof ModelConfig>(key: Key, value: ModelConfig[Key]) {
        edited.current.add(key);
        setConfig(previous => ({...previous, [key]: value}))
    }

    function changeTask(task: string) {
        if (!options) return
        for (const key of ["task", "metric", "threshold"] as const) edited.current.add(key)
        setConfig(previous => taskDraft(previous, task, options))
    }

    function applyTemplate(template: {task: string; metric: string; description: string; split?: string}) {
        if (!options) return
        for (const key of ["task", "metric", "threshold", "description", "split"] as const) edited.current.add(key)
        const task = fieldChoices(options, "task", config).includes(template.task) ? template.task : options.defaults.task
        const draft = taskDraft(config, task, options)
        draft.description = template.description
        if (fieldChoices(options, "metric", draft).includes(template.metric)) draft.metric = template.metric
        if (template.split && fieldChoices(options, "split", draft).includes(template.split)) draft.split = template.split
        setConfig(draft)
        setError("")
        if (fieldInputProps(options, "timeColumn", draft).required) setAdvanced(true)
    }

    const choices = {
        task: fieldChoices(options, "task", config),
        metric: fieldChoices(options, "metric", config),
        split: fieldChoices(options, "split", config),
        strategy: fieldChoices(options, "strategy", config),
        algorithms: fieldChoices(options, "algorithms", config),
    }
    const inputProps = (key: keyof ModelConfig) => fieldInputProps(options, key, config)

    function newTask(source?: ModelConfig, experiment?: Experiment) {
        setParent(experiment && session && !demo ? {...experiment, sessionId: session.id} : undefined)
        setOpenId(null)
        edited.current = new Set(source ? Object.keys(source) as (keyof ModelConfig)[] : [])
        setConfig(source ? {...source, name: source.name + " · 继续探索"} : {...(options?.defaults ?? defaultModelConfig)})
        setError("");
        setTab("experiments");
        setSelectedId(0);
        setFilter("all")
    }

    function openTask(id: string) {
        setOpenId(id);
        setTab("experiments");
        setSelectedId(0);
        setFilter("all");
        setError("");
        setNotice("")
    }

    async function start(event: FormEvent) {
        event.preventDefault()
        if (launchLock.current || running || controller.runningId) return
        if (!optionsReady) {
            setError("配置选项尚未加载，请稍后重试。");
            return
        }
        launchLock.current = true;
        setStarting(true);
        setError("");
        setNotice("")
        try {
            const created = await controller.create({
                config, ...(parent ? {
                    parentSessionId: parent.sessionId,
                    parentExperimentId: parent.id
                } : {})
            })
            setOpenId(created.id);
            setTab("experiments");
            setSelectedId(0)
            await controller.run(created.id, undefined, event => setLiveLogs(previous => ({
                ...previous,
                [created.id]: appendModelLog(previous[created.id] ?? [], event)
            })))
        } catch (reason) {
            setError(String(reason))
        } finally {
            launchLock.current = false;
            setStarting(false)
        }
    }

    async function stop() {
        if (!running || stopping) return
        setStopping(true);
        setError("")
        try {
            await controller.stop(running.id);
            setNotice("已发送停止请求，正在等待当前执行结束。")
        } catch (reason) {
            setError(`停止失败：${String(reason)}`)
        } finally {
            setStopping(false)
        }
    }

    async function runIdleTask() {
        if (!session || busy) return
        try {
            await controller.run(session.id)
        } catch (reason) {
            setError(String(reason))
        }
    }

    async function removeTask() {
        if (!session || busy) return
        try {
            await controller.remove(session.id);
            setOpenId(null)
        } catch (reason) {
            setError(String(reason))
        }
    }

    function download() {
        const text = `# ${currentConfig.name}\n\n${demo ? "演示任务：所有指标仅作界面示例。" : `状态：${session ? statusLabels[session.status] : "新建"}`}\n\n## 配置\n\n\`\`\`json\n${JSON.stringify(currentConfig, null, 2)}\n\`\`\`\n\n## 实验记录\n\n${experiments.map(item => `### 步骤 ${item.id} · ${item.title}\n\n${currentConfig.metric}: ${item.score}\n\n${item.plan}\n\n${item.result}`).join("\n\n")}\n\n## 执行输出\n\n${session?.output ?? "演示报告，不包含真实模型产物。"}`
        const url = URL.createObjectURL(new Blob([text], {type: "text/markdown;charset=utf-8"}))
        const link = document.createElement("a");
        link.href = url;
        link.download = `modeling-${demo ? "demo" : session?.id ?? "report"}.md`;
        link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
        setNotice("报告已导出为 Markdown。")
    }


    return {
        sidebarWidth,
        setSidebarWidth,
        sidebarCollapsed,
        setSidebarCollapsed,
        openId,
        config,
        tab,
        setTab,
        setSelectedId,
        filter,
        setFilter,
        detailTab,
        setDetailTab,
        advanced,
        setAdvanced,
        search,
        setSearch,
        notice,
        setNotice,
        starting,
        stopping,
        parent,
        setParent,
        sessions,
        error,
        setError,
        demo,
        warnings,
        session,
        currentConfig,
        snapshot,
        experiments,
        best,
        selected,
        running,
        viewing,
        improvement,
        metricDirection,
        filtered,
        change,
        changeTask,
        applyTemplate,
        choices,
        inputProps,
        newTask,
        openTask,
        start,
        stop,
        download,
        busy,
        optionsReady,
        runIdleTask,
        removeTask
    }
}

import {useCallback, useEffect, useRef, useState} from "react"
import type {CSSProperties, FormEvent, ReactNode} from "react"
import {normalizeMessages, readError, readEventStream} from "./api.ts"
import {Markdown as RenderMarkdown} from "./components.tsx"
import {
    appendModelLog,
    bestExperiment,
    buildModelPrompt,
    defaultModelConfig,
    demoConfig,
    demoExperiments,
    lowerIsBetter,
    modelLogsFromMessages,
    parseModelReport,
    validateModelConfig
} from "./modeling.ts"
import type {Experiment, ModelConfig, ModelLog} from "./modeling.ts"
import ModelEvolution from "./ModelEvolution.tsx"
import ModelExecutionLogs from "./ModelExecutionLogs.tsx"
import SessionSidebarDivider from "./SessionSidebarDivider.tsx"
import "./SelfModeling.css"

type ModelStatus = "running" | "complete" | "stopped" | "error" | "interrupted"
type ModelSession = { id: string; config: ModelConfig; status: ModelStatus; output: string; logs?: ModelLog[]; updatedAt: number }
type Tab = "experiments" | "analysis" | "config" | "logs"
const STORAGE_KEY = "vh-modeling-sessions-v1"
const statusLabels: Record<ModelStatus, string> = {
    running: "探索中",
    complete: "执行结束",
    stopped: "已停止",
    error: "执行失败",
    interrupted: "待核实"
}
const templates = [
    {
        title: "信贷风险预测",
        detail: "二分类 · 稳定性与可解释性",
        task: "二分类",
        metric: "AUC-ROC",
        description: "建立信贷违约预测模型，比较特征筛选和梯度提升算法。在提升 AUC 的同时关注跨月稳定性与模型可解释性，禁止使用贷后信息。"
    },
    {
        title: "客户流失识别",
        detail: "二分类 · 召回与精准触达",
        task: "二分类",
        metric: "F1",
        description: "预测客户流失风险，关注类别不平衡，比较采样、特征组合和模型参数，以 F1 为主指标评估泛化能力。"
    },
    {
        title: "业务指标预测",
        detail: "回归 · 误差与泛化能力",
        task: "回归",
        metric: "RMSE",
        description: "建立业务指标回归预测模型，使用时间切分评估，比较特征工程和回归算法，以 RMSE 为目标最小化预测误差。"
    },
]

function loadSessions(): ModelSession[] {
    try {
        const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]")
        if (!Array.isArray(saved)) return []
        return saved.filter((item): item is ModelSession => item && typeof item.id === "string" && item.config && typeof item.config.description === "string" && Array.isArray(item.config.algorithms) && typeof item.output === "string" && typeof item.updatedAt === "number" && Object.hasOwn(statusLabels, item.status)).map(item => ({
            ...item,
            config: {...defaultModelConfig, ...item.config}
        }))
    } catch {
        return []
    }
}

function Icon({kind = "tree", size = 20}: {
    kind?: "tree" | "orbit" | "plus" | "arrow" | "chart" | "check" | "data";
    size?: number
}) {
    const paths = {
        tree: "M10 2h4v4h-4zM12 6v5M4 11h16M4 11v5m8-5v5m8-5v5M2 16h4v4H2zM10 16h4v4h-4zM18 16h4v4h-4z",
        orbit: "M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1",
        plus: "M12 5v14M5 12h14",
        arrow: "M5 12h14m-5-5 5 5-5 5",
        chart: "M4 4v16h16M7 15l4-5 4 2 5-7",
        check: "m5 12 4 4L19 6",
        data: "M4 7c0-5 16-5 16 0s-16 5-16 0Zm0 0v10c0 5 16 5 16 0V7M4 12c0 5 16 5 16 0"
    }
    return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={paths[kind]}/>
        {kind === "orbit" && <circle cx="12" cy="12" r="4"/>}</svg>
}

function Field({label, children, hint}: { label: string; children: ReactNode; hint?: string }) {
    return <label className="model-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

function Markdown({content}: { content: string }) {
    return <RenderMarkdown text={content}/>
}

export default function SelfModeling() {
    const [sidebarWidth, setSidebarWidth] = useState<number | undefined>(undefined)
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
    const [sessions, setSessions] = useState<ModelSession[]>(loadSessions)
    const [openId, setOpenId] = useState<string | null>(null)
    const [config, setConfig] = useState<ModelConfig>({...defaultModelConfig})
    const [tab, setTab] = useState<Tab>("experiments")
    const [selectedId, setSelectedId] = useState(0)
    const [filter, setFilter] = useState("all")
    const [detailTab, setDetailTab] = useState("plan")
    const [advanced, setAdvanced] = useState(false)
    const [search, setSearch] = useState("")
    const [error, setError] = useState("")
    const [notice, setNotice] = useState("")
    const [starting, setStarting] = useState(false)
    const [stopping, setStopping] = useState(false)
    const [parent, setParent] = useState<Experiment | undefined>()
    const streamId = useRef<string | null>(null)
    const launchLock = useRef(false)
    const demo = openId === "demo"
    const session = sessions.find(item => item.id === openId)
    const currentConfig = demo ? demoConfig : session?.config ?? config
    const experiments = demo ? demoExperiments : parseModelReport(session?.output ?? "")
    const best = bestExperiment(experiments, currentConfig.metric)
    const baseline = experiments[0]
    const selected = experiments.find(item => item.id === selectedId) ?? baseline
    const running = sessions.find(item => item.status === "running")
    const viewing = demo || !!session
    const improvement = best && baseline ? (best.score - baseline.score) * (lowerIsBetter(currentConfig.metric) ? -1 : 1) : null
    const filtered = experiments.filter(item => filter === "all" || (filter === "best" ? item.id === best?.id : baseline && (lowerIsBetter(currentConfig.metric) ? item.score < baseline.score : item.score > baseline.score)))

    const updateSession = useCallback((id: string, patch: Partial<ModelSession>) => setSessions(previous => previous.map(item => item.id === id ? {...item, ...patch} : item)), [])

    useEffect(() => {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
        } catch {
            queueMicrotask(() => setNotice("浏览器存储不可用或空间不足，本次记录仍可查看；请导出报告保存。"))
        }
    }, [sessions])

    useEffect(() => {
        const pending = sessions.filter(item => item.status === "running" && item.id !== streamId.current)
        if (!pending.length) return
        let active = true
        const refresh = async () => {
            try {
                const listResponse = await fetch("/api/sessions", {cache: "no-store"})
                if (!listResponse.ok) return
                const list = await listResponse.json() as { running_id: string | null }
                for (const item of pending) {
                    const response = await fetch(`/api/sessions/${encodeURIComponent(item.id)}`, {cache: "no-store"})
                    if (!active) return
                    if (!response.ok) {
                        if (response.status === 404) updateSession(item.id, {status: "error"})
                        continue
                    }
                    const data = await response.json() as { messages: unknown }
                    const messages = normalizeMessages(data.messages)
                    const output = messages.filter(message => message.role === "assistant").map(message => message.content).join("\n\n")
                    const logs = modelLogsFromMessages(messages)
                    if (active) updateSession(item.id, {output, ...(logs.length ? {logs} : {}), ...(list.running_id !== item.id ? {status: "interrupted" as const} : {})})
                }
            } catch {
                if (active) setNotice("暂时无法同步任务状态，正在重试。")
            }
        }
        const timer = window.setInterval(() => void refresh(), 4000)
        return () => {
            active = false;
            clearInterval(timer)
        }
    }, [sessions, updateSession])

    function change<Key extends keyof ModelConfig>(key: Key, value: ModelConfig[Key]) {
        setConfig(previous => ({...previous, [key]: value}))
    }

    function newTask(source?: ModelConfig, experiment?: Experiment) {
        setOpenId(null);
        setConfig(source ? {...source, name: `${source.name || "建模任务"} · 继续探索`} : {...defaultModelConfig})
        setParent(experiment);
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
        if (launchLock.current || running) return
        const invalid = validateModelConfig(config)
        if (invalid) {
            setError(invalid);
            return
        }
        launchLock.current = true;
        setStarting(true);
        setError("");
        setNotice("")
        let id: string | null = null
        try {
            const response = await fetch("/api/sessions", {method: "POST"})
            if (!response.ok) throw new Error(await readError(response))
            const data = await response.json() as { id: string }
            id = data.id
            const modeResponse = await fetch(`/api/sessions/${encodeURIComponent(id)}/mode`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({mode: "plan"})
            })
            if (!modeResponse.ok) throw new Error(await readError(modeResponse))
            const savedConfig = {
                ...config,
                name: config.name.trim() || `${config.task}建模 · ${new Date().toLocaleDateString("zh-CN")}`
            }
            streamId.current = id
            setSessions(previous => [{
                id: id!,
                config: savedConfig,
                status: "running",
                output: "",
                updatedAt: Date.now()
            }, ...previous])
            setOpenId(id);
            setTab("experiments");
            setSelectedId(0)
            const messageResponse = await fetch(`/api/sessions/${encodeURIComponent(id)}/messages`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({text: buildModelPrompt(savedConfig, parent)})
            })
            if (!messageResponse.ok) throw new Error(await readError(messageResponse))
            let output = ""
            let logs: ModelLog[] = []
            const result = await readEventStream(messageResponse, event => {
                const nextLogs = appendModelLog(logs, event)
                if (event.origin !== "child" && event.kind === "text_delta" && typeof event.text === "string") {
                    output += event.text
                }
                if (nextLogs !== logs) updateSession(id!, {output, logs: nextLogs})
                logs = nextLogs
            })
            if (result.completed) {
                const status: ModelStatus = result.status === "error" ? "error" : result.status === "stopped" ? "stopped" : ["complete", "completed", "success", "done"].includes(result.status ?? "") ? "complete" : "interrupted"
                updateSession(id, {status, updatedAt: Date.now()})
            } else setNotice("连接已中断，正在从服务端同步任务。任务不会重复提交。")
            try {
                const finalResponse = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {cache: "no-store"})
                if (finalResponse.ok) {
                    const finalData = await finalResponse.json() as { messages: unknown }
                    const messages = normalizeMessages(finalData.messages)
                    const finalOutput = messages.filter(message => message.role === "assistant").map(message => message.content).join("\n\n")
                    updateSession(id, {...(finalOutput ? {output: finalOutput} : {}), logs: logs.length ? logs : modelLogsFromMessages(messages)})
                }
            } catch {
                setNotice("已保留实时输出，最终记录暂时无法同步。")
            }
        } catch (reason) {
            setError(`任务未能正常执行：${reason instanceof Error ? reason.message : String(reason)}`)
            if (id) updateSession(id, {status: "error"})
        } finally {
            streamId.current = null;
            launchLock.current = false;
            setStarting(false)
        }
    }

    async function stop() {
        if (!running || stopping) return
        setStopping(true);
        setError("")
        try {
            const response = await fetch(`/api/sessions/${encodeURIComponent(running.id)}/stop`, {method: "POST"})
            if (!response.ok) throw new Error(await readError(response))
            setNotice("已发送停止请求，正在等待当前执行结束。")
        } catch (reason) {
            setError(`停止失败：${String(reason)}`)
        } finally {
            setStopping(false)
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

    const basicFields = <>
        <Field label="任务名称"><input value={config.name} onChange={event => change("name", event.target.value)}
                                       placeholder="选填，留空自动命名" maxLength={100}/></Field>
        <Field label="建模目标 *"><textarea value={config.description}
                                            onChange={event => change("description", event.target.value)}
                                            placeholder="描述要解决的问题、评估目标和业务约束…" rows={5}
                                            required/></Field>
        <Field label="数据文件路径 *" hint="填写工作目录内的 CSV / Parquet 路径"><input value={config.dataPath}
                                                                                        onChange={event => change("dataPath", event.target.value)}
                                                                                        placeholder="data/train.csv"
                                                                                        required/></Field>
        <div className="model-field-grid"><Field label="目标列 *"><input value={config.target}
                                                                         onChange={event => change("target", event.target.value)}
                                                                         placeholder="如 default_flag"
                                                                         required/></Field><Field
            label="任务类型"><select value={config.task} onChange={event => {
            change("task", event.target.value);
            change("metric", event.target.value === "回归" ? "RMSE" : "AUC-ROC");
            change("threshold", event.target.value === "回归" ? 1 : 0.85)
        }}>
            <option>二分类</option>
            <option>多分类</option>
            <option>回归</option>
        </select></Field></div>
        <div className="model-field-grid"><Field label="评估指标"><select value={config.metric}
                                                                          onChange={event => change("metric", event.target.value)}>{(config.task === "回归" ? ["RMSE", "MAE"] : ["AUC-ROC", "F1", "Accuracy", "Log Loss"]).map(item =>
            <option key={item}>{item}</option>)}</select></Field><Field
            label={`目标值 ${lowerIsBetter(config.metric) ? "≤" : "≥"}`}><input type="number" step="any" min="0"
                                                                                max={lowerIsBetter(config.metric) ? undefined : 1}
                                                                                value={config.threshold}
                                                                                onChange={event => change("threshold", event.target.valueAsNumber)}
                                                                                required/></Field></div>
    </>

    return <div className="model-app">
        <aside id="modeling-session-sidebar" className={`model-sidebar ${sidebarCollapsed ? "is-collapsed" : ""}`} style={{"--model-sidebar-width": sidebarWidth === undefined ? undefined : `${sidebarWidth}px`} as CSSProperties}>
            <div className="model-brand"><Icon/><div className="model-brand-name"><strong>auto-research</strong><small>自进化建模</small></div><span>BETA</span></div>
            <button className="model-new" onClick={() => newTask()}><Icon kind="plus" size={16}/>新建建模任务</button>
            <div className="model-sidebar-section"><span>建模工作台</span></div>
            <button className={`model-side-link ${!viewing ? "is-active" : ""}`} onClick={() => newTask()}><Icon
                kind="data" size={16}/>任务配置<span>↗</span></button>
            <button className={`model-side-link ${demo ? "is-active" : ""}`} onClick={() => openTask("demo")}><Icon
                kind="chart" size={16}/>示例实验<span className="model-demo-tag">演示</span></button>
            <div className="model-sidebar-section"><span>历史任务</span><span>{sessions.length}</span></div>
            {sessions.length > 0 &&
                <input className="model-search" aria-label="搜索历史任务" placeholder="搜索任务…" value={search}
                       onChange={event => setSearch(event.target.value)}/>}
            <div
                className="model-history">{sessions.filter(item => item.config.name.toLowerCase().includes(search.toLowerCase())).map(item =>
                <button className={`model-history-item ${openId === item.id ? "is-active" : ""}`} key={item.id}
                        onClick={() => openTask(item.id)}><span><i
                    className={`model-status-dot ${item.status}`}/>{item.config.name}</span><small><span className={`model-history-status ${item.status}`}>{statusLabels[item.status]}</span> · {new Date(item.updatedAt).toLocaleDateString("zh-CN")}</small>
                </button>)}{!sessions.length &&
                <p className="model-history-empty">每一次探索，都会留在这里。</p>}{sessions.length > 0 && !sessions.some(item => item.config.name.toLowerCase().includes(search.toLowerCase())) &&
                <p className="model-history-empty">没有匹配的任务</p>}</div>
            <div className="model-sidebar-footer"><span className="model-footer-icon"><Icon size={17}/></span>
                <div>从一个目标，到更优模型<small>配置 · 实验 · 评估 · 迭代</small></div>
            </div>
        </aside>
        <SessionSidebarDivider sidebarId="modeling-session-sidebar" collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(value => !value)} onResize={setSidebarWidth}/>
        <main className="model-main">
            <header className="model-topbar">
                <div><span>自进化建模</span><span
                    className="model-breadcrumb">/</span><strong>{viewing ? "实验工作区" : "新建任务"}</strong></div>
                <div className="model-topbar-right"><span
                    className="model-private-dot"/>{demo ? "示例工作区" : "本地工作区"}{viewing &&
                    <button className="model-button" onClick={download}>导出报告 ↗</button>}</div>
            </header>
            {error && <div className="model-alert error" role="alert">{error}
                <button aria-label="关闭错误提示" onClick={() => setError("")}>×</button>
            </div>}
            {notice && <div className="model-alert" role="status">{notice}
                <button aria-label="关闭通知" onClick={() => setNotice("")}>×</button>
            </div>}
            {!viewing ? <div className="model-create-scroll">
                <div className="model-intro">
                    <div className="model-eyebrow"><Icon size={16}/> SELF-EVOLVING MODELING</div>
                    <h1>让模型，在探索中进化。</h1><p>定义目标，交给智能体探索特征、训练模型、验证假设。<br/>每一次迭代都有迹可循，每一个改进都有数据支撑。
                </p></div>
                <div className="model-create-layout">
                    <form className="model-config-card" onSubmit={event => void start(event)}>
                        <div className="model-card-heading"><span className="model-number">01</span>
                            <div><h2>定义建模任务</h2><p>一个清晰的目标，是好模型的起点。</p></div>
                        </div>
                        {parent && <div className="model-parent-note">基于步骤 {parent.id}「{parent.title}」继续探索
                            <button type="button" onClick={() => setParent(undefined)}>移除</button>
                        </div>}
                        {basicFields}
                        <button type="button" className="model-advanced-toggle" aria-expanded={advanced}
                                onClick={() => setAdvanced(!advanced)}>
                            <span>搜索策略与高级配置</span><span>{advanced ? "收起 −" : "展开 +"}</span></button>
                        {advanced && <div className="model-advanced">
                            <div className="model-field-grid"><Field label="测试集切分"><select value={config.split}
                                                                                                onChange={event => change("split", event.target.value)}>
                                <option value="random">随机切分</option>
                                <option value="time">时间切分</option>
                            </select></Field><Field label="测试集比例 (%)"><input type="number" min="5" max="40"
                                                                                  value={config.testRatio}
                                                                                  onChange={event => change("testRatio", event.target.valueAsNumber)}
                                                                                  required/></Field></div>
                            {config.split === "time" && <Field label="时间字段 *"><input value={config.timeColumn}
                                                                                         onChange={event => change("timeColumn", event.target.value)}
                                                                                         placeholder="如 apply_month"
                                                                                         required/></Field>}
                            <div className="model-field-grid"><Field label="最大探索步数"><input type="number" min="1"
                                                                                                 max="500"
                                                                                                 value={config.maxSteps}
                                                                                                 onChange={event => change("maxSteps", event.target.valueAsNumber)}
                                                                                                 required/></Field><Field
                                label="时间预算 (小时)"><input type="number" min="0.1" max="24" step="0.1"
                                                               value={config.hours}
                                                               onChange={event => change("hours", event.target.valueAsNumber)}
                                                               required/></Field></div>
                            <div className="model-field-grid"><Field label="搜索策略"><select value={config.strategy}
                                                                                              onChange={event => change("strategy", event.target.value)}>
                                <option>多路择优</option>
                                <option>顺序迭代</option>
                            </select></Field><Field label="每轮候选方案"><input type="number" min="1" max="5"
                                                                                value={config.parallel}
                                                                                onChange={event => change("parallel", event.target.valueAsNumber)}
                                                                                required/></Field></div>
                            <fieldset className="model-algorithms">
                                <legend>探索算法 <small>不选则由智能体选择</small></legend>
                                {["LightGBM", "XGBoost", "CatBoost", "RandomForest"].map(algorithm => <label
                                    key={algorithm}><input type="checkbox"
                                                           checked={config.algorithms.includes(algorithm)}
                                                           onChange={() => change("algorithms", config.algorithms.includes(algorithm) ? config.algorithms.filter(item => item !== algorithm) : [...config.algorithms, algorithm])}/>{algorithm}
                                </label>)}</fieldset>
                            <Field label="业务约束"><textarea rows={3} value={config.constraints}
                                                              onChange={event => change("constraints", event.target.value)}
                                                              placeholder="如 PSI < 0.2；排除泄露字段；保留缺失值…"/></Field>
                            <p className="model-budget-note">预算由智能体按指令执行；实际并发与耗时取决于可用资源。</p>
                        </div>}
                        <div className="model-submit-row">
                            <span>最多 {config.maxSteps} 步 · {config.hours} 小时预算</span>
                            <button type="submit" className="model-primary"
                                    disabled={starting || !!running}>{starting ? "正在创建…" : running ? "已有任务运行中" : "开始探索"}<Icon
                                kind="arrow" size={16}/></button>
                        </div>
                        {running && <button type="button" className="model-text-button"
                                            onClick={() => openTask(running.id)}>查看正在运行的任务 →</button>}
                    </form>
                    <div className="model-guide-column">
                        <section className="model-workflow"><span
                            className="model-kicker">A CONTINUOUS LEARNING LOOP</span><h2>不止训练一次，<br/>而是持续寻找更优解。
                        </h2>
                            <div className="model-loop-visual">
                                <div className="model-orbit-ring"/>
                                <div className="model-orbit-core"><Icon size={28}/><span>自动迭代</span></div>
                                <span className="model-orbit-node node-top">提出假设</span><span
                                className="model-orbit-node node-right">训练实验</span><span
                                className="model-orbit-node node-bottom">评估结果</span><span
                                className="model-orbit-node node-left">择优进化</span></div>
                            <ol className="model-process">
                                <li><b>建立可靠基线</b><span>检查数据质量，固定评估方式</span></li>
                                <li><b>探索多个方向</b><span>特征、算法与参数的联合优化</span></li>
                                <li><b>留下可复现的结果</b><span>对比实验，输出最优方案与报告</span></li>
                            </ol>
                            <button className="model-example-button" onClick={() => openTask("demo")}>先看看一次完整的探索<Icon
                                kind="arrow" size={16}/></button>
                        </section>
                        <section className="model-templates"><h3>从常见场景开始 <span>快速填入目标</span>
                        </h3>{templates.map(template => <button key={template.title} onClick={() => {
                            setConfig(previous => ({
                                ...previous,
                                description: template.description,
                                task: template.task,
                                metric: template.metric,
                                threshold: template.task === "回归" ? 1 : 0.85,
                                split: template.task === "回归" ? "time" : previous.split
                            }));
                            setError("");
                            if (template.task === "回归") setAdvanced(true)
                        }}><span><b>{template.title}</b><small>{template.detail}</small></span><Icon kind="arrow"
                                                                                                     size={15}/>
                        </button>)}</section>
                    </div>
                </div>
                <p className="model-page-footnote">数据留在你的工作环境中 · 评估结果来自实际执行 · 全过程可追溯</p>
            </div> : <>
                <section className="model-task-heading">
                    <div className="model-task-title">
                        <div><span className="model-kicker">MODELING WORKSPACE</span><h1>{currentConfig.name}</h1>
                            <p>{currentConfig.task} <span>·</span> {currentConfig.target}
                                <span>·</span> {currentConfig.strategy}</p></div>
                        <div className="model-task-actions"><span
                            className={`model-state ${demo ? "demo" : session?.status}`}>{demo ? "演示任务" : session && statusLabels[session.status]}</span>{running?.id === openId &&
                            <button className="model-button" disabled={stopping}
                                    onClick={() => void stop()}>{stopping ? "正在发送…" : "停止探索"}</button>}</div>
                    </div>
                    {demo && <div className="model-demo-banner"><span>示例预览</span>以下数据用于体验完整流程，不代表真实训练结果。
                        <button onClick={() => newTask()}>创建自己的任务 →</button>
                    </div>}
                    <div className="model-stats">
                        <div><span>主评估指标</span><strong>{currentConfig.metric}<small>验证集</small></strong></div>
                        <div><span>当前最优</span><strong
                            className="model-score">{best?.score.toFixed(5) ?? "—"}<small>{best ? `步骤 ${best.id}` : "等待评估"}</small></strong>
                        </div>
                        <div>
                            <span>较基线改善</span><strong>{improvement === null ? "—" : `${improvement >= 0 ? "+" : ""}${improvement.toFixed(5)}`}<small>指标绝对值</small></strong>
                        </div>
                        <div>
                            <span>有效实验</span><strong>{experiments.length}<small>/ {currentConfig.maxSteps} 步预算</small></strong>
                        </div>
                    </div>
                </section>
                <nav className="model-tabs"
                     aria-label="建模任务视图">{([["experiments", "实验详情"], ["analysis", "结果分析"], ["config", "任务配置"], ["logs", "执行日志"]] as const).map(([id, title]) =>
                    <button key={id} className={tab === id ? "is-active" : ""}
                            aria-current={tab === id ? "page" : undefined}
                            onClick={() => setTab(id)}>{title}{id === "experiments" &&
                        <span>{experiments.length}</span>}</button>)}</nav>
                <div className="model-workspace-body">
                    {tab === "experiments" && <div className="model-experiment-layout">
                        <aside className="model-experiment-list">
                            <div className="model-list-title">演进实验 <span>{experiments.length} 个方案</span></div>
                            <div
                                className="model-filters">{[["all", "全部"], ["improved", "有提升"], ["best", "最优"]].map(([id, label]) =>
                                <button key={id} onClick={() => setFilter(id)}
                                        className={filter === id ? "is-active" : ""}>{label}</button>)}</div>
                            <div className="model-step-scroll">{filtered.map(item => <button key={item.id}
                                                                                             className={`model-step ${item.id === selected?.id ? "is-selected" : ""}`}
                                                                                             onClick={() => {
                                                                                                 setSelectedId(item.id);
                                                                                                 setDetailTab("plan")
                                                                                             }}>
                                <div><span className="model-step-number">{String(item.id).padStart(2, "0")}</span><span
                                    className="model-step-title">{item.title}<small>{item.algorithm || "实验方案"}</small></span>{item.id === best?.id &&
                                    <span className="model-best-tag">最优</span>}</div>
                                <footer><span>{item.score.toFixed(5)}</span><span>{item.duration || "—"}</span></footer>
                            </button>)}{!filtered.length && <div
                                className="model-empty-small">{experiments.length ? "暂无符合条件的方案" : "首轮实验完成后，方案将显示在这里。"}</div>}</div>
                        </aside>
                        <section className="model-experiment-detail">{selected ? <>
                                <div className="model-detail-heading">
                                    <div><span
                                        className="model-kicker">EXPERIMENT {String(selected.id).padStart(2, "0")}</span>
                                        <h2>{selected.title}</h2></div>
                                    <button className="model-button" disabled={!!running || starting}
                                            onClick={() => newTask(currentConfig, selected)}>基于此方案继续探索 ↗
                                    </button>
                                </div>
                                <div className="model-detail-score">
                                    <span>{currentConfig.metric}</span><strong>{selected.score.toFixed(5)}</strong><span
                                    className="model-valid-tag"><Icon kind="check"
                                                                      size={13}/>{demo ? "示例评估" : "验证集评估"}</span>
                                </div>
                                <div
                                    className="model-detail-tabs">{[["plan", "计划与结果"], ["code", "实验源码"]].map(([id, title]) =>
                                    <button className={detailTab === id ? "is-active" : ""} key={id}
                                            onClick={() => setDetailTab(id)}>{title}</button>)}</div>
                                {detailTab === "plan" ? <div className="model-plan-content">
                                    <article><h3><span className="model-number">01</span>探索思路</h3>
                                        <p>{selected.plan || "该实验未提供计划说明。"}</p></article>
                                    <div className="model-plan-connector">↓</div>
                                    <article className="model-result-card"><h3><Icon kind="check" size={17}/>评估结果</h3>
                                        <p>{selected.result || "查看执行日志了解完整评估过程。"}</p></article>
                                    <div className="model-detail-meta">
                                        <span>算法 <b>{selected.algorithm || "未提供"}</b></span><span>耗时 <b>{selected.duration || "未提供"}</b></span><span>评估 <b>固定验证集</b></span>
                                    </div>
                                    <div className="model-next-hint"><Icon kind="orbit"
                                                                           size={18}/><span>每一步都是可追溯的实验。你可以从任意方案继续探索，形成新的建模任务。</span>
                                    </div>
                                </div> : <div className="model-code">{demo &&
                                    <p>示例片段，用于展示源码视图；数据变量需在实际训练脚本中定义。</p>}{selected.code ?
                                    <Markdown content={`\`\`\`python\n${selected.code}\n\`\`\``}/> : <div
                                        className="model-empty-small">此实验未附带源码。真实任务的源码与产物路径可在执行日志中查看。</div>}</div>}</> :
                            <div className="model-waiting">
                                <div className="model-waiting-icon"><Icon size={34}/></div>
                                <h2>{session?.status === "running" ? "智能体正在探索建模方案" : "暂未生成结构化实验结果"}</h2>
                                <p>数据检查、基线训练和评估结果会逐步呈现。<br/>你可以在执行日志中查看实际进展。</p>
                                <button className="model-button" onClick={() => setTab("logs")}>查看执行日志 →</button>
                            </div>}</section>
                    </div>}
                    {tab === "analysis" && <div className="model-analysis">
                        <div className="model-section-heading"><h2>每一次探索，都有迹可循</h2>
                            <span>{experiments.length} 次有效实验</span></div>
                        <ModelEvolution experiments={experiments} metric={currentConfig.metric} onSelect={id => {
                            setSelectedId(id);
                            setTab("experiments")
                        }}/>{best && <section className="model-best-summary">
                        <div className="model-best-symbol"><Icon kind="chart" size={24}/></div>
                        <div><span className="model-kicker">BEST EXPERIMENT · 步骤 {best.id}</span><h2>{best.title}</h2>
                            <p>{best.plan}</p>
                            <p>相较基线，{currentConfig.metric} 改善 {improvement?.toFixed(5)}。{demo ? "当前仅为演示分析，真实任务以实际评估结果为准。" : "该结论基于验证集；测试集结论请查看最终报告。"}</p>
                        </div>
                        <button className="model-button" onClick={() => {
                            setSelectedId(best.id);
                            setTab("experiments")
                        }}>查看方案 ↗
                        </button>
                    </section>}
                        <section className="model-comparison"><h3>模型对比</h3>
                            <div className="model-table-scroll">
                                <table>
                                    <thead>
                                    <tr>
                                        <th>实验方案</th>
                                        <th>算法</th>
                                        <th>{currentConfig.metric}</th>
                                        <th>较基线改善</th>
                                        <th>耗时</th>
                                    </tr>
                                    </thead>
                                    <tbody>{[...experiments].sort((first, second) => lowerIsBetter(currentConfig.metric) ? first.score - second.score : second.score - first.score).map(item =>
                                        <tr key={item.id}>
                                            <td>
                                                <button className="model-text-button" onClick={() => {
                                                    setSelectedId(item.id);
                                                    setTab("experiments")
                                                }}>步骤 {item.id} · {item.title}</button>
                                                {item.id === best?.id && <span className="model-best-tag">最优</span>}
                                            </td>
                                            <td>{item.algorithm || "—"}</td>
                                            <td>{item.score.toFixed(5)}</td>
                                            <td>{((item.score - baseline!.score) * (lowerIsBetter(currentConfig.metric) ? -1 : 1)).toFixed(5)}</td>
                                            <td>{item.duration || "—"}</td>
                                        </tr>)}</tbody>
                                </table>
                            </div>
                            {!experiments.length &&
                                <div className="model-empty-small">实际评估完成后生成模型对比。</div>}</section>
                    </div>}
                    {tab === "config" && <section className="model-config-summary">
                        <div className="model-section-heading"><h2>任务配置</h2>
                            <button className="model-button" onClick={() => newTask(currentConfig)}>复制为新任务 ↗
                            </button>
                        </div>
                        <p>{currentConfig.description}</p>
                        <dl>{[["数据路径", currentConfig.dataPath], ["目标列", currentConfig.target], ["任务类型", currentConfig.task], ["评估目标", `${currentConfig.metric} ${lowerIsBetter(currentConfig.metric) ? "≤" : "≥"} ${currentConfig.threshold}`], ["测试集划分", `${currentConfig.split === "time" ? `时间切分 · ${currentConfig.timeColumn}` : "随机切分"} · ${currentConfig.testRatio}%`], ["探索算法", currentConfig.algorithms.join(" / ") || "自动选择"], ["搜索策略", currentConfig.strategy], ["预算", `${currentConfig.maxSteps} 步 / ${currentConfig.hours} 小时 / 每轮 ${currentConfig.parallel} 个候选`], ["约束", currentConfig.constraints || "未设置"]].map(([label, value]) =>
                            <div key={label}>
                                <dt>{label}</dt>
                                <dd>{value}</dd>
                            </div>)}</dl>
                    </section>}
                    {tab === "logs" && <section className="model-log-panel">
                        <div className="model-section-heading"><h2>执行日志</h2>
                            <span>{demo ? "演示说明" : session && statusLabels[session.status]}</span></div>
                        {demo ? <Markdown
                            content="### 示例任务说明\n\n此工作区展示 12 个实验方案的演进、指标对比和配置。所有指标均为演示数据。\n\n真实任务会在这里显示智能体的数据检查、训练过程、工具执行后的结论与最终报告。\n\n点击「新建建模任务」，填写本地数据路径与目标列，即可通过现有智能体运行真实任务。"/> : session?.logs?.length ?
                            <ModelExecutionLogs key={session.id} logs={session.logs}/> : session?.output.trim() ?
                            <Markdown
                                content={session.output.replace(/```modeling-report\s*\n[\s\S]*?```/g, "\n> 已将结构化评估结果同步至实验详情。\n")}/> :
                            <div
                                className="model-empty-small">{session?.status === "running" ? "任务已提交，等待智能体输出…" : "暂无执行输出。请检查服务与数据路径后重新创建任务。"}</div>}
                    </section>}
                </div>
            </>}
        </main>
    </div>
}

import {useEffect, useRef, useState} from "react"
import type {FormEvent, KeyboardEvent} from "react"
import {useTasks} from "../tasks/useTasks.ts"
import type {ResearchSnapshot} from "./types.ts"

export function useDeepResearch() {

    const [sidebarWidth, setSidebarWidth] = useState<number | undefined>(undefined)
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
    const [openId, setOpenId] = useState<string | null>(() => {
        try {
            return localStorage.getItem("vh-research-open")
        } catch {
            return null
        }
    })
    const [topicDraft, setTopicDraft] = useState("")
    const [engine, setEngine] = useState<"advanced" | "standard">("advanced")
    const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
    const [copied, setCopied] = useState(false)
    const [logOpen, setLogOpen] = useState(false)
    const [queriesOpen, setQueriesOpen] = useState(false)
    const [followUpDraft, setFollowUpDraft] = useState("")
    const [instructionOpen, setInstructionOpen] = useState(false)
    const [copiedInstruction, setCopiedInstruction] = useState(false)
    const [starting, setStarting] = useState(false)
    const launchLock = useRef(false)
    const controller = useTasks<ResearchSnapshot>("deepresearch", openId)
    const {tasks: sessions, error: errorText, setError: setErrorText} = controller
    const task = sessions.find(item => item.id === openId)
    const detail = openId ? controller.details[openId] : undefined
    const openSession = task ? {
        ...task,
        topic: task.topic ?? task.config.topic ?? "深度研究",
        messages: detail?.messages ?? []
    } : null
    const warnings = detail?.warnings ?? []
    const sessionDone = openSession?.status === "completed"
    const isRunning = openSession?.status === "running" || controller.streamingId === openId && openId !== null
    const running = starting || !!controller.streamingId || !!controller.runningId || sessions.some(item => item.status === "running")
    const activeTaskId = controller.streamingId ?? sessions.find(item => item.status === "running")?.id
    const tasks = openSession?.tasks ?? []
    const progress = openSession?.progress ?? {done: 0, total: 0}
    const selectedTask = tasks.find(item => item.id === selectedTaskId) ?? null
    const selectedTaskIndex = selectedTask ? tasks.indexOf(selectedTask) : null

    function setSelectedTaskIndex(index: number | null) {
        setSelectedTaskId(index === null ? null : tasks[index]?.id ?? null)
    }

    const taskDetail = selectedTask ? openSession?.details?.[selectedTask.id] ?? null : null
    const totalEvents = openSession?.messages.length ?? 0
    useEffect(() => {
        if (controller.loaded && openId && !sessions.some(session => session.id === openId)) {
            setOpenId(null)
            setSelectedTaskId(null)
        }
    }, [openId, sessions, controller.loaded])
    useEffect(() => {
        try {
            if (openId) localStorage.setItem("vh-research-open", openId)
            else localStorage.removeItem("vh-research-open")
        } catch {
        }
    }, [openId])

    async function startResearch() {
        if (launchLock.current || running || !topicDraft.trim()) return
        launchLock.current = true
        setStarting(true)
        setErrorText("")
        try {
            const created = await controller.create({topic: topicDraft.trim(), engine})
            setOpenId(created.id)
            setSelectedTaskIndex(null)
            await controller.run(created.id)
        } catch (reason) {
            setErrorText(String(reason))
        } finally {
            launchLock.current = false;
            setStarting(false)
        }
    }

    async function stopResearch() {
        if (!activeTaskId) return
        try {
            await controller.stop(activeTaskId)
        } catch (reason) {
            setErrorText(String(reason))
        }
    }

    async function runIdleTask() {
        if (!openId || running) return
        try {
            await controller.run(openId)
        } catch (reason) {
            setErrorText(String(reason))
        }
    }

    async function removeTask() {
        if (!openId || running) return
        try {
            await controller.remove(openId);
            setOpenId(null);
            setSelectedTaskId(null)
        } catch (reason) {
            setErrorText(String(reason))
        }
    }

    async function sendFollowUp() {
        if (!openId || running || !followUpDraft.trim()) return
        const text = followUpDraft.trim()
        setErrorText("")
        try {
            await controller.run(openId, text);
            setFollowUpDraft("")
        } catch (reason) {
            setErrorText(String(reason))
        }
    }

    function onTopicKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            void startResearch()
        }
    }

    function onFormSubmit(event: FormEvent) {
        event.preventDefault();
        void startResearch()
    }

    function switchSession(id: string) {
        setOpenId(id);
        setSelectedTaskIndex(null);
        setLogOpen(false);
        setInstructionOpen(false)
        setFollowUpDraft("")
        setErrorText("")
    }

    function newTask() {
        setOpenId(null)
        setTopicDraft("")
        setEngine("advanced")
        setSelectedTaskId(null)
        setFollowUpDraft("")
        setLogOpen(false)
        setInstructionOpen(false)
        setQueriesOpen(false)
        setErrorText("")
    }

    function copyPath(value: string) {
        void navigator.clipboard.writeText(value).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500)
        })
    }

    const statusLabels = {
        idle: "等待开始",
        running: "研究进行中",
        completed: "研究完成",
        stopped: "已停止",
        error: "研究出错",
        interrupted: "执行中断"
    }
    const statusLabel = isRunning ? statusLabels.running : statusLabels[openSession?.status ?? "idle"]
    const statusClass = isRunning ? "research-status-running" : sessionDone ? "research-status-done" : openSession?.status === "error" ? "research-status-error" : "research-status-idle"

    return {
        sidebarWidth,
        setSidebarWidth,
        sidebarCollapsed,
        setSidebarCollapsed,
        openId,
        topicDraft,
        setTopicDraft,
        engine,
        setEngine,
        selectedTaskIndex,
        setSelectedTaskIndex,
        copied,
        logOpen,
        setLogOpen,
        queriesOpen,
        setQueriesOpen,
        followUpDraft,
        setFollowUpDraft,
        instructionOpen,
        setInstructionOpen,
        copiedInstruction,
        setCopiedInstruction,
        sessions,
        errorText,
        openSession,
        warnings,
        sessionDone,
        isRunning,
        running,
        starting,
        newTask,
        tasks,
        progress,
        selectedTask,
        taskDetail,
        totalEvents,
        statusLabel,
        statusClass,
        stopResearch,
        sendFollowUp,
        onTopicKeyDown,
        onFormSubmit,
        switchSession,
        copyPath,
        activeTaskId,
        runIdleTask,
        removeTask
    }
}

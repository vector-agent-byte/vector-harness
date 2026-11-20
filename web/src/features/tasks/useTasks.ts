import {useCallback, useEffect, useRef, useState} from "react"
import {taskApi, TaskHttpError} from "./api.ts"
import type {TaskBase, TaskCreate, TaskDetail, TaskKind} from "./api.ts"
import {importLegacy} from "./legacy.ts"
import type {StreamEvent} from "../../types.ts"

export function useTasks<Task extends TaskBase>(kind: TaskKind, selectedId: string | null) {
    const [api] = useState(() => taskApi<Task>(kind))
    const [tasks, setTasks] = useState<Task[]>([])
    const [details, setDetails] = useState<Record<string, TaskDetail<Task>>>({})
    const [error, setError] = useState("")
    const [streamingId, setStreamingId] = useState<string | null>(null)
    const [runningId, setRunningId] = useState<string | null>(null)
    const [loaded, setLoaded] = useState(false)
    const active = useRef(false)
    const locked = useRef(false)
    const streams = useRef(new Set<AbortController>())
    const revisions = useRef(new Map<string, number>())
    const generations = useRef(new Map<string, number>())
    const listGeneration = useRef(0)
    const knownIds = useRef(new Set<string>())
    const removedIds = useRef(new Set<string>())
    const current = useRef({tasks, selectedId, streamingId})
    current.current = {tasks, selectedId, streamingId}

    const mergeTask = useCallback((task: Task) => {
        if (removedIds.current.has(task.id)) return
        knownIds.current.add(task.id)
        setTasks(previous => previous.some(item => item.id === task.id) ? previous.map(item => item.id === task.id ? {...item, ...task} : item) : [task, ...previous])
    }, [])

    const forgetTask = useCallback((id: string) => {
        listGeneration.current += 1
        removedIds.current.add(id)
        knownIds.current.delete(id)
        generations.current.set(id, (generations.current.get(id) ?? 0) + 1)
        revisions.current.delete(id)
        setTasks(previous => previous.filter(task => task.id !== id))
        setDetails(previous => {
            const next = {...previous}
            delete next[id]
            return next
        })
        setRunningId(previous => previous === id ? null : previous)
    }, [])

    const reload = useCallback(async (id: string) => {
        if (removedIds.current.has(id)) return null
        const generation = (generations.current.get(id) ?? 0) + 1
        generations.current.set(id, generation)
        let detail: TaskDetail<Task>
        try {
            detail = await api.detail(id)
        } catch (reason) {
            if (!active.current || generations.current.get(id) !== generation) return null
            if (reason instanceof TaskHttpError && reason.status === 404) {
                forgetTask(id)
                return null
            }
            if (current.current.selectedId === id || current.current.streamingId === id || current.current.tasks.some(task => task.id === id && task.status === "running")) throw reason
            return null
        }
        if (active.current && !removedIds.current.has(id) && generations.current.get(id) === generation && (detail.task.revision === undefined || detail.task.revision >= (revisions.current.get(id) ?? -1))) {
            if (detail.task.revision !== undefined) revisions.current.set(id, detail.task.revision)
            mergeTask(detail.task)
            setDetails(previous => ({...previous, [id]: detail}))
        }
        return detail
    }, [api, mergeTask, forgetTask])

    const refresh = useCallback(async () => {
        const generation = ++listGeneration.current
        let list: Awaited<ReturnType<typeof api.list>>
        try {
            list = await api.list()
        } catch (reason) {
            if (active.current && generation === listGeneration.current) throw reason
            return
        }
        if (!active.current || generation !== listGeneration.current) return
        const listedIds = new Set(list.tasks.map(task => task.id))
        for (const id of new Set([...knownIds.current, ...generations.current.keys()])) {
            if (!listedIds.has(id) && !removedIds.current.has(id)) forgetTask(id)
        }
        for (const task of list.tasks) {
            removedIds.current.delete(task.id)
            if (task.revision !== undefined && task.revision > (revisions.current.get(task.id) ?? -1)) revisions.current.set(task.id, task.revision)
        }
        knownIds.current = listedIds
        setLoaded(true)
        setRunningId(list.running_id)
        setTasks(previous => list.tasks.map(task => {
            const existing = previous.find(item => item.id === task.id)
            return task.revision !== undefined && task.revision < (existing?.revision ?? -1) ? existing! : {...existing, ...task}
        }))
        const ids = new Set([current.current.selectedId, current.current.streamingId, ...list.tasks.filter(task => task.status === "running").map(task => task.id), ...current.current.tasks.filter(task => task.status === "running").map(task => task.id)].filter((id): id is string => !!id && listedIds.has(id)))
        await Promise.all([...ids].map(reload))
    }, [api, reload, forgetTask])

    useEffect(() => {
        active.current = true
        let cancelled = false
        let refreshing = false
        const sync = async () => {
            if (refreshing || cancelled) return
            refreshing = true
            try {
                await refresh()
            } catch (reason) {
                if (!cancelled) setError(String(reason))
            } finally {
                refreshing = false
            }
        }
        void (async () => {
            try {
                await importLegacy(kind, localStorage)
            } finally {
                if (!cancelled) await sync()
            }
        })().catch(() => undefined)
        const timer = window.setInterval(() => void sync(), 3000)
        const controllers = streams.current
        return () => {
            cancelled = true;
            active.current = false;
            listGeneration.current += 1;
            generations.current.forEach((generation, id) => generations.current.set(id, generation + 1));
            clearInterval(timer);
            controllers.forEach(controller => controller.abort())
        }
    }, [kind, refresh])

    useEffect(() => {
        let cancelled = false
        if (selectedId && selectedId !== "demo") void reload(selectedId).catch(reason => {
            if (active.current && !cancelled && current.current.selectedId === selectedId) setError(String(reason))
        })
        return () => {cancelled = true}
    }, [selectedId, reload])

    const run = async (id: string, text?: string, onEvent?: (event: StreamEvent) => void) => {
        if (locked.current) throw new Error("已有任务正在提交。")
        locked.current = true
        setStreamingId(id)
        setError("")
        const controller = new AbortController()
        streams.current.add(controller)
        revisions.current.delete(id)
        const receive = (event: StreamEvent) => {
            if (!active.current || removedIds.current.has(id)) return
            if (event.kind === "task_snapshot" && event.task && typeof event.task === "object") {
                const task = event.task as Task
                const revision = typeof event.revision === "number" ? event.revision : 0
                if (task.id === id && revision > (revisions.current.get(id) ?? -1)) {
                    revisions.current.set(id, revision)
                    generations.current.set(id, (generations.current.get(id) ?? 0) + 1)
                    mergeTask({...task, revision})
                    setDetails(previous => ({
                        ...previous,
                        [id]: {...(previous[id] ?? {messages: [], warnings: []}), task}
                    }))
                }
            }
            onEvent?.(event)
        }
        try {
            if (text === undefined) await api.run(id, receive, controller.signal)
            else await api.message(id, text, receive, controller.signal)
        } finally {
            streams.current.delete(controller)
            locked.current = false
            if (active.current) {
                setStreamingId(null)
                await reload(id)
                await refresh()
            }
        }
    }

    return {
        tasks, details, error, setError, streamingId, runningId, loaded, reload, refresh, run,
        create: async (body: TaskCreate<Task>) => {
            const task = await api.create(body);
            listGeneration.current += 1;
            removedIds.current.delete(task.id);
            mergeTask(task);
            return task
        },
        stop: async (id: string) => {
            await api.stop(id);
            await reload(id)
        },
        remove: async (id: string) => {
            try {await api.remove(id)} catch (reason) {
                if (!(reason instanceof TaskHttpError && reason.status === 404)) throw reason
            }
            forgetTask(id)
        },
    }
}

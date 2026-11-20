import { useCallback, useEffect, useRef, useState } from "react"
import type { Dispatch, MouseEvent, RefObject, SetStateAction } from "react"
import { entryMenu as entryMenuLabels, findListableDir, listingGenerationIsCurrent, refreshMayReplaceDraft, REFRESH_MS, viewedPathAfter } from "../../dirPath.ts"
import { parseDirs, readError } from "../../api.ts"
import { errorLabel, viewedPath } from "../../format.ts"
import type { DirListing, EntryKind, EntryMenu, FilePreview, NamedPath } from "../../types.ts"
import { agentRequests, fileBytesUrl } from "./api.ts"

type FileContext = {
  runningId: string | null
  readingStreamRef: RefObject<boolean>
  setErrorText: Dispatch<SetStateAction<string | null>>
  setSkillOpen: Dispatch<SetStateAction<boolean>>
}

export function useAgentFiles({ runningId, readingStreamRef, setErrorText, setSkillOpen }: FileContext) {
  const [workdir, setWorkdir] = useState("")
  const [pickerOpen, setPickerOpen] = useState(false)
  const [browse, setBrowse] = useState<DirListing | null>(null)
  const [pickerBrowse, setPickerBrowse] = useState<DirListing | null>(null)
  const [pickerError, setPickerError] = useState<string | null>(null)
  const [pathDraft, setPathDraft] = useState("")
  const [entryMenu, setEntryMenu] = useState<EntryMenu | null>(null)
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [renameTarget, setRenameTarget] = useState<(NamedPath & { draft: string }) | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<NamedPath | null>(null)
  const entryMenuRef = useRef<HTMLDivElement | null>(null)
  const viewedPathRef = useRef("")
  const viewGenerationRef = useRef(0)
  const pickerOpenRef = useRef(false)
  const workdirRef = useRef("")
  pickerOpenRef.current = pickerOpen
  workdirRef.current = workdir
  const loadDirs = useCallback(async (
    path: string,
    target: "view" | "picker" = "view",
    replaceDraft = true,
  ): Promise<DirListing | null> => {
    const generation = target === "view" ? (viewGenerationRef.current += 1) : 0
    try {
      const response = await agentRequests.dirs(path)
      if (!response.ok) {
        const code = response.status >= 400 && response.status < 500 ? await readError(response) : "bad_request"
        if (target === "picker") setPickerError(errorLabel(code))
        else if (listingGenerationIsCurrent(generation, viewGenerationRef.current)) setErrorText(code)
        return null
      }
      const listing = parseDirs(await response.json())
      if (!listing) return null
      if (target === "picker") {
        setPickerError(null)
        setPickerBrowse(listing)
        setPathDraft(listing.path)
        return listing
      }
      if (!listingGenerationIsCurrent(generation, viewGenerationRef.current)) return null
      viewedPathRef.current = viewedPathAfter(viewedPathRef.current, listing.path)
      setBrowse(listing)
      if (replaceDraft && refreshMayReplaceDraft(pickerOpenRef.current)) setPathDraft(listing.path)
      return listing
    } catch {
      if (target !== "picker" && listingGenerationIsCurrent(generation, viewGenerationRef.current)) {
        setErrorText("bad_request")
      }
      return null
    }
  }, [setErrorText])

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (pickerOpenRef.current) return
      const path = viewedPathRef.current || workdirRef.current
      if (path === "") return
      void loadDirs(path, "view", refreshMayReplaceDraft(false))
    }, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [loadDirs])

  useEffect(() => {
    void (async () => {
      try {
        const response = await agentRequests.workdir()
        if (!response.ok) return
        const body = await response.json() as { path?: unknown }
        if (typeof body.path !== "string") return
        setWorkdir(body.path)
        await loadDirs(body.path)
      } catch {}
    })()
  }, [loadDirs])

  useEffect(() => {
    if (!pickerOpen) return
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setPickerOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [pickerOpen])
  useEffect(() => {
    if (entryMenu === null) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target
      if (target instanceof Node && entryMenuRef.current?.contains(target)) return
      setEntryMenu(null)
    }
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setEntryMenu(null)
    }
    window.addEventListener("pointerdown", onPointerDown)
    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("pointerdown", onPointerDown)
      window.removeEventListener("keydown", onKey)
    }
  }, [entryMenu])

  function refreshListing() {
    const path = viewedPathRef.current || workdirRef.current
    if (path === "") return
    void loadDirs(path, "view", refreshMayReplaceDraft(pickerOpenRef.current))
  }

  function openEntryMenu(event: MouseEvent<HTMLElement>, kind: EntryKind, name: string, path: string) {
    event.preventDefault()
    event.stopPropagation()
    const labels = entryMenuLabels(kind)
    const width = 140
    const height = labels.length * 32 + 12
    setEntryMenu({
      kind,
      name,
      path,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8)),
    })
  }

  async function openPreview(path: string, name: string) {
    setEntryMenu(null)
    try {
      const response = await agentRequests.file(path)
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) setErrorText(await readError(response))
        return
      }
      const body = (await response.json()) as { kind?: unknown; text?: unknown }
      const kind = body.kind
      if (kind !== "text" && kind !== "image" && kind !== "too_large" && kind !== "unsupported") return
      setPreview({
        name,
        path,
        kind,
        text: typeof body.text === "string" ? body.text : "",
      })
    } catch {
      setErrorText("bad_request")
    }
  }

  function downloadEntry(path: string) {
    setEntryMenu(null)
    const link = document.createElement("a")
    link.href = fileBytesUrl(path)
    document.body.append(link)
    link.click()
    link.remove()
  }

  async function submitRename() {
    if (renameTarget === null) return
    try {
      const response = await agentRequests.renameFile(renameTarget.path, renameTarget.draft)
      if (!response.ok) {
        setErrorText(await readError(response))
        return
      }
      setRenameTarget(null)
      setErrorText(null)
      refreshListing()
    } catch {
      setErrorText("bad_request")
    }
  }

  async function confirmDelete() {
    if (deleteTarget === null) return
    try {
      const response = await agentRequests.deleteFile(deleteTarget.path)
      if (!response.ok) {
        setErrorText(await readError(response))
        return
      }
      setDeleteTarget(null)
      setErrorText(null)
      refreshListing()
    } catch {
      setErrorText("bad_request")
    }
  }

  function chooseEntryAction(label: string, menu: EntryMenu) {
    if (label === "查看") {
      void openPreview(menu.path, menu.name)
      return
    }
    if (label === "下载") {
      downloadEntry(menu.path)
      return
    }
    if (label === "重命名") {
      setEntryMenu(null)
      setRenameTarget({ name: menu.name, path: menu.path, draft: menu.name })
      return
    }
    if (label === "删除") {
      setEntryMenu(null)
      setDeleteTarget({ name: menu.name, path: menu.path })
    }
  }

  async function openPicker() {
    pickerOpenRef.current = true
    setPickerOpen(true)
    setPickerError(null)
    setSkillOpen(false)
    setPathDraft(workdir)
    const found = await findListableDir(workdir, async (path) => (await loadDirs(path, "picker")) !== null)
    if (!found) {
      setPickerError("不是文件夹")
      return
    }
    if (found.relocated) setPickerError("原来的工作目录已经不在，请另选一个文件夹。")
  }

  async function chooseDirectory(path: string) {
    if (runningId !== null || readingStreamRef.current) {
      setErrorText("busy")
      return
    }
    try {
      const response = await agentRequests.setWorkdir(path)
      if (!response.ok) {
        setErrorText(await readError(response))
        return
      }
      const body = (await response.json()) as { path?: unknown }
      if (typeof body.path !== "string") return
      setWorkdir(body.path)
      setPickerOpen(false)
      setErrorText(null)
      await loadDirs(body.path)
    } catch {
      setErrorText("bad_request")
    }
  }

  const viewed = browse && workdir && browse.path !== workdir ? viewedPath(workdir, browse.path) : null

  return { workdir, browse, pickerOpen, setPickerOpen, pickerBrowse, pickerError, pathDraft, setPathDraft, entryMenu, entryMenuRef, preview, setPreview, renameTarget, setRenameTarget, deleteTarget, setDeleteTarget, viewed, loadDirs, refreshListing, openEntryMenu, openPreview, downloadEntry, submitRename, confirmDelete, chooseEntryAction, openPicker, chooseDirectory }
}

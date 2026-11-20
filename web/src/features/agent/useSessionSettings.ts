import { useCallback, useEffect, useRef, useState } from "react"
import type { Dispatch, RefObject, SetStateAction } from "react"
import { normalizeMode } from "../../modes.ts"
import type { ModeId } from "../../modes.ts"
import { sessionSkillSelection } from "../../skills.ts"
import type { SkillSelection } from "../../skills.ts"
import { parseSkills, readError } from "../../api.ts"
import { errorLabel } from "../../format.ts"
import type { SessionItem, SkillItem } from "../../types.ts"
import { agentRequests } from "./api.ts"

type SettingsContext = {
  openSession: SessionItem | null
  openIdRef: RefObject<string | null>
  runningId: string | null
  readingStreamRef: RefObject<boolean>
  sendingRef: RefObject<boolean>
  savingModeRef: RefObject<boolean>
  savingSkillsRef: RefObject<boolean>
  settingsRevisionRef: RefObject<number>
  setSessions: Dispatch<SetStateAction<SessionItem[]>>
  setErrorText: Dispatch<SetStateAction<string | null>>
}

export function useSessionSettings({ openSession, openIdRef, runningId, readingStreamRef, sendingRef, savingModeRef, savingSkillsRef, settingsRevisionRef, setSessions, setErrorText }: SettingsContext) {
  const [savingMode, setSavingMode] = useState(false)
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [skillOpen, setSkillOpen] = useState(false)
  const [skillDraft, setSkillDraft] = useState<SkillSelection>(null)
  const [skillSearch, setSkillSearch] = useState("")
  const [skillError, setSkillError] = useState<string | null>(null)
  const [savingSkills, setSavingSkills] = useState(false)
  const skillSessionRef = useRef<string | null>(null)
  const loadSkills = useCallback(async () => {
    try {
      const response = await agentRequests.skills()
      if (!response.ok) return
      setSkills(parseSkills(await response.json()))
    } catch {
      setSkills([])
    }
  }, [])


  useEffect(() => { void loadSkills() }, [loadSkills])
  useEffect(() => {
    if (!skillOpen) return
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && !savingSkillsRef.current) setSkillOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [skillOpen, savingSkillsRef])

  async function chooseMode(mode: ModeId) {
    const sessionId = openIdRef.current
    if (!sessionId || runningId !== null || readingStreamRef.current || sendingRef.current || savingModeRef.current || savingSkillsRef.current) return
    savingModeRef.current = true
    settingsRevisionRef.current += 1
    setSavingMode(true)
    try {
      const response = await agentRequests.setMode(sessionId, mode)
      if (!response.ok) {
        setErrorText(await readError(response))
        return
      }
      const body = (await response.json()) as { mode?: unknown }
      setSessions(current => current.map(item => item.id === sessionId ? { ...item, mode: normalizeMode(body.mode) } : item))
      setErrorText(null)
    } catch {
      setErrorText("bad_request")
    } finally {
      settingsRevisionRef.current += 1
      savingModeRef.current = false
      setSavingMode(false)
    }
  }

  function openSkillPicker() {
    if (!openSession || runningId !== null || readingStreamRef.current || savingMode || savingSkills) return
    skillSessionRef.current = openSession.id
    setSkillDraft(openSession.skills === null ? null : [...openSession.skills])
    setSkillSearch("")
    setSkillError(null)
    setSkillOpen(true)
    void loadSkills()
  }

  async function saveSkills() {
    const sessionId = skillSessionRef.current
    if (!sessionId || runningId !== null || readingStreamRef.current || sendingRef.current || savingSkillsRef.current || savingModeRef.current) return
    savingSkillsRef.current = true
    settingsRevisionRef.current += 1
    setSavingSkills(true)
    setSkillError(null)
    try {
      const response = await agentRequests.setSkills(sessionId, skillDraft)
      if (!response.ok) {
        setSkillError(errorLabel(await readError(response)))
        return
      }
      const body = (await response.json()) as Record<string, unknown>
      setSessions((current) =>
        current.map((item) => (item.id === sessionId ? { ...item, skills: sessionSkillSelection(body) } : item)),
      )
      setErrorText(null)
      setSkillOpen(false)
    } catch {
      setSkillError("技能选择保存失败，请重试")
    } finally {
      settingsRevisionRef.current += 1
      savingSkillsRef.current = false
      setSavingSkills(false)
    }
  }

  const skillOptions = [
    ...skills,
    ...(skillDraft ?? []).filter(name => !skills.some(skill => skill.name === name))
      .map(name => ({ name, description: "当前不可用，请取消选择后保存" })),
  ].filter(skill => `${skill.name} ${skill.description}`.toLowerCase().includes(skillSearch.trim().toLowerCase()))

  return { skills, savingMode, savingSkills, skillOpen, setSkillOpen, skillDraft, setSkillDraft, skillSearch, setSkillSearch, skillError, skillOptions, chooseMode, openSkillPicker, saveSkills }
}

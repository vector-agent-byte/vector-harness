import { useEffect, useState } from "react"
import type { AppView } from "../../appViews.ts"
import { useAgentSession } from "./useAgentSession.ts"
import { useAgentFiles } from "./useAgentFiles.ts"
import { useAgentLayout } from "./useAgentLayout.ts"
import { useTranscriptNavigation } from "./useTranscriptNavigation.ts"

export function useAgentWorkspace(appView: AppView) {
  const session = useAgentSession(appView === "home")
  const files = useAgentFiles(session)
  const [sidebarWidth, setSidebarWidth] = useState(220)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [viewMode, setViewMode] = useState<"chat" | "trace" | "chain">("chat")
  const navigation = useTranscriptNavigation({ ...session, appView, viewMode })
  const { skillOpen, propsId, setPropsId } = session
  const { pickerOpen, preview, renameTarget, deleteTarget } = files
  const dialogKey = skillOpen ? "skills" : pickerOpen ? "picker" : preview ? "preview" : renameTarget ? "rename" : deleteTarget ? "delete" : propsId ? "props" : ""
  const layout = useAgentLayout(dialogKey)

  useEffect(() => {
    if (propsId === null || pickerOpen) return
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setPropsId(null)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [propsId, pickerOpen, setPropsId])

  return { session, files, layout, navigation, sidebarWidth, setSidebarWidth, sidebarCollapsed, setSidebarCollapsed, viewMode, setViewMode }
}

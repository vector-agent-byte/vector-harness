import type { useAgentWorkspace } from "./useAgentWorkspace.ts"
import { AgentSidebar } from "./AgentSidebar.tsx"
import { AgentConversation } from "./AgentConversation.tsx"
import { AgentFilePanel } from "./AgentFilePanel.tsx"
import { AgentSkillDialog } from "./AgentSkillDialog.tsx"
import { AgentFileDialogs } from "./AgentFileDialogs.tsx"
import { AgentSessionDialogs } from "./AgentSessionDialogs.tsx"

export function AgentWorkspace({ agent }: { agent: ReturnType<typeof useAgentWorkspace> }) {
  const { session, files, layout, navigation, viewMode, setViewMode } = agent
  return (
    <>
      <AgentSidebar {...agent} />
      <AgentConversation session={session} navigation={navigation} viewMode={viewMode} setViewMode={setViewMode} />
      <AgentFilePanel files={files} layout={layout} inputLocked={session.inputLocked} />
      <AgentSkillDialog session={session} layout={layout} />
      <AgentFileDialogs files={files} layout={layout} />
      <AgentSessionDialogs session={session} layout={layout} />
    </>
  )
}

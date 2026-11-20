import { toggleSkill } from "../../skills.ts"
import type { useAgentSession } from "./useAgentSession.ts"
import type { useAgentLayout } from "./useAgentLayout.ts"

export function AgentSkillDialog({ session, layout }: { session: ReturnType<typeof useAgentSession>; layout: ReturnType<typeof useAgentLayout> }) {
  const { skills, runningId, skillOpen, setSkillOpen, savingSkills, skillSearch, setSkillSearch, skillDraft, setSkillDraft, skillOptions, skillError, saveSkills } = session
  const { dialogFrame, beginDialogDrag, beginDialogResize } = layout

  return (
    <>
      {skillOpen ? (
        <div className="props-backdrop" onClick={() => { if (!savingSkills) setSkillOpen(false) }}>
          <div
            {...dialogFrame("picker-dialog skills-dialog")}
            role="dialog"
            aria-modal="true"
            aria-labelledby="skills-dialog-title"
            onClick={event => event.stopPropagation()}
          >
            <div id="skills-dialog-title" className="props-heading" onPointerDown={beginDialogDrag}>选择会话技能</div>
            <p className="skills-dialog-hint">技能仅应用于当前会话，保存后刷新或重新打开仍会保留。全选会自动包含新增技能。</p>
            <div className="skills-toolbar">
              <div className="skills-search">
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
                  <circle cx="8.5" cy="8.5" r="5.5" />
                  <path d="m13 13 4 4" />
                </svg>
                <input
                  type="search"
                  aria-label="搜索技能"
                  placeholder="搜索技能名称或说明…"
                  value={skillSearch}
                  onChange={event => setSkillSearch(event.target.value)}
                />
              </div>
              <div className="skills-bulk-actions" role="group" aria-label="批量选择技能">
                <button type="button" aria-pressed={skillDraft === null} disabled={savingSkills} onClick={() => setSkillDraft(null)}>
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="m3 8 3 3 7-7" />
                  </svg>
                  全选
                </button>
                <button type="button" aria-pressed={skillDraft !== null && skillDraft.length === 0} disabled={savingSkills} onClick={() => setSkillDraft([])}>
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
                    <path d="M4 8h8" />
                  </svg>
                  全不选
                </button>
              </div>
            </div>
            <div className="skills-selection-count" aria-live="polite">
              {skillDraft === null ? `已全选 · ${skills.length} 项技能` : `已选择 ${skillDraft.length} 项技能`}
            </div>
            <div className="skills-grid" role="group" aria-label="可选技能">
              {skillOptions.map(skill => {
                const checked = skillDraft === null || skillDraft.includes(skill.name)
                return (
                  <label key={skill.name} className={`skill-card${checked ? " is-selected" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={savingSkills}
                      onChange={() => setSkillDraft(current => toggleSkill(current, skill.name, skills.map(item => item.name)))}
                    />
                    <span className="skill-card-content">
                      <span className="skill-name">{skill.name}</span>
                      <span className="skill-description">{skill.description}</span>
                    </span>
                  </label>
                )
              })}
              {skillOptions.length === 0 ? <div className="skill-empty">{skills.length === 0 ? "没有可选择的技能" : "没有匹配的技能"}</div> : null}
            </div>
            {skillError ? <div className="picker-error" role="alert">{skillError}</div> : null}
            <div className="dir-actions">
              <button type="button" disabled={savingSkills} onClick={() => setSkillOpen(false)}>取消</button>
              <button type="button" className="skills-save" disabled={savingSkills || runningId !== null} onClick={() => void saveSkills()}>
                {savingSkills ? "正在保存…" : "保存选择"}
              </button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
    </>
  )
}

export type SkillSelection = string[] | null

export function sessionSkillSelection(record: Record<string, unknown>): SkillSelection {
  if (!("skills" in record)) return typeof record.skill === "string" && record.skill ? [record.skill] : null
  if (record.skills === null) return null
  if (!Array.isArray(record.skills)) return []
  return [...new Set(record.skills.filter((name): name is string => typeof name === "string" && name.trim() !== ""))]
}

export function skillSelectionLabel(selection: SkillSelection): string {
  if (selection === null) return "全部技能"
  if (selection.length === 0) return "不使用技能"
  if (selection.length === 1) return selection[0]
  return `已选 ${selection.length} 项技能`
}

export function toggleSkill(selection: SkillSelection, name: string, available: string[]): string[] {
  const names = selection ?? available
  return names.includes(name) ? names.filter(item => item !== name) : [...names, name]
}

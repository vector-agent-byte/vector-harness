/** 选择工作目录的路径回退。工作目录被删掉时，弹框仍要出现，并落到最近的现存上级。 */

export function shouldShowPicker(open: boolean, hasListing: boolean): boolean {
  void hasListing
  return open
}

export const REFRESH_MS = 3000

export function listingIsCurrent(requested: string, current: string): boolean {
  return requested === current
}

export function refreshMayReplaceDraft(pickerOpen: boolean): boolean {
  return !pickerOpen
}

export function entryMenu(kind: "file" | "dir"): string[] {
  if (kind === "dir") return ["重命名", "删除"]
  return ["查看", "重命名", "下载", "删除"]
}

function parentPath(path: string): string | null {
  const trimmed = path.trim().replace(/[\\/]+$/, "")
  if (trimmed === "" || /^[A-Za-z]:$/.test(trimmed)) return null
  const slash = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"))
  if (slash < 0) return null
  if (slash === 0) return trimmed[0] === "/" ? "/" : null
  const parent = trimmed.slice(0, slash)
  if (/^[A-Za-z]:$/.test(parent)) return `${parent}\\`
  return parent
}

export async function findListableDir(
  start: string,
  list: (path: string) => Promise<boolean>,
): Promise<{ path: string; relocated: boolean } | null> {
  let current = start
  let relocated = false
  const seen = new Set<string>()
  while (current !== "" && !seen.has(current)) {
    seen.add(current)
    if (await list(current)) return { path: current, relocated }
    const parent = parentPath(current)
    if (parent === null || parent === current) return null
    current = parent
    relocated = true
  }
  return null
}

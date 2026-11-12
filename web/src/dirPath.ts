/** 选择工作目录的路径回退。工作目录被删掉时，弹框仍要出现，并落到最近的现存上级。 */

export function shouldShowPicker(open: boolean, hasListing: boolean): boolean {
  void hasListing
  return open
}

export const REFRESH_MS = 3000

export function listingIsCurrent(requested: string, current: string): boolean {
  return requested === current
}

export function listingGenerationIsCurrent(requestGeneration: number, latestGeneration: number): boolean {
  return requestGeneration === latestGeneration
}

export function viewedPathAfter(previous: string, loaded: string | null): string {
  if (loaded === null || loaded === "") return previous
  return loaded
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

export type CodeToken = {
  text: string
  kind: "plain" | "comment" | "string" | "keyword" | "number"
}

const PY_WORDS = new Set(
  "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield".split(" "),
)
const JS_WORDS = new Set(
  "break case catch class const continue default delete do else export extends false finally for function if import in instanceof let new null return static super switch this throw true try typeof var void while with yield".split(" "),
)
const JS_SUFFIXES = new Set([".js", ".jsx", ".ts", ".tsx"])

function suffixOf(name: string): string {
  const dot = name.lastIndexOf(".")
  return dot < 0 ? "" : name.slice(dot).toLowerCase()
}

function readString(source: string, start: number): number {
  const quote = source[start]
  const triple = source.startsWith(quote + quote + quote, start)
  const closer = triple ? quote + quote + quote : quote
  let i = start + closer.length
  while (i < source.length) {
    if (source.startsWith(closer, i)) return i + closer.length
    if (!triple && (source[i] === "\n" || source[i] === "\r")) return i
    i += source[i] === "\\" ? 2 : 1
  }
  return source.length
}

export function highlightCode(source: string, name: string): CodeToken[] {
  const suffix = suffixOf(name)
  const keywords = suffix === ".py" ? PY_WORDS : JS_SUFFIXES.has(suffix) ? JS_WORDS : null
  const hashComment = suffix === ".py" || suffix === ".sh"
  const slashComment = JS_SUFFIXES.has(suffix) || suffix === ".css"
  const tokens: CodeToken[] = []
  let i = 0
  const push = (text: string, kind: CodeToken["kind"]) => {
    if (text !== "") tokens.push({ text, kind })
  }
  while (i < source.length) {
    const ch = source[i]
    if (hashComment && ch === "#") {
      const end = source.indexOf("\n", i)
      const stop = end < 0 ? source.length : end
      push(source.slice(i, stop), "comment")
      i = stop
      continue
    }
    if (slashComment && ch === "/" && source[i + 1] === "/") {
      const end = source.indexOf("\n", i)
      const stop = end < 0 ? source.length : end
      push(source.slice(i, stop), "comment")
      i = stop
      continue
    }
    if (ch === '"' || ch === "'") {
      const end = readString(source, i)
      push(source.slice(i, end), "string")
      i = end
      continue
    }
    if (keywords && /[A-Za-z_]/.test(ch)) {
      let end = i + 1
      while (end < source.length && /[A-Za-z0-9_]/.test(source[end])) end += 1
      const word = source.slice(i, end)
      push(word, keywords.has(word) ? "keyword" : "plain")
      i = end
      continue
    }
    if (/[0-9]/.test(ch)) {
      let end = i + 1
      while (end < source.length && /[0-9.]/.test(source[end])) end += 1
      push(source.slice(i, end), "number")
      i = end
      continue
    }
    let end = i + 1
    while (end < source.length) {
      const next = source[end]
      if (next === '"' || next === "'") break
      if (hashComment && next === "#") break
      if (slashComment && next === "/" && source[end + 1] === "/") break
      if (keywords && /[A-Za-z_]/.test(next)) break
      if (/[0-9]/.test(next)) break
      end += 1
    }
    push(source.slice(i, end), "plain")
    i = end
  }
  return tokens
}

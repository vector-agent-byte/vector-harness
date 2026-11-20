import type { ModeId } from "../../modes.ts"
import type { SkillSelection } from "../../skills.ts"

export { readEventStream } from "../../api.ts"

export function fileBytesUrl(path: string, inline = false) {
  return `/api/file/bytes?path=${encodeURIComponent(path)}${inline ? "&inline=1" : ""}`
}

export function agentApi(transport: typeof fetch = fetch) {
  const sessionPath = (id: string) => `/api/sessions/${encodeURIComponent(id)}`
  const get = (url: string) => transport(url, { cache: "no-store" })
  const post = (url: string, body: unknown) => transport(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })

  return {
    listSessions: () => get("/api/sessions?kind=agent"),
    session: (id: string) => get(sessionPath(id)),
    createSession: () => transport("/api/sessions", { method: "POST" }),
    deleteSession: (id: string) => transport(sessionPath(id), { method: "DELETE" }),
    setMode: (id: string, mode: ModeId) => post(`${sessionPath(id)}/mode`, { mode }),
    setSkills: (id: string, names: SkillSelection) => post(`${sessionPath(id)}/skills`, { names }),
    sendMessage: (id: string, text: string) => post(`${sessionPath(id)}/messages`, { text }),
    stopSession: (id: string) => transport(`${sessionPath(id)}/stop`, { method: "POST" }),
    skills: () => get("/api/skills"),
    workdir: () => get("/api/workdir"),
    setWorkdir: (path: string) => post("/api/workdir", { path }),
    dirs: (path: string) => get(`/api/dirs${path === "" ? "" : `?path=${encodeURIComponent(path)}`}`),
    file: (path: string) => get(`/api/file?path=${encodeURIComponent(path)}`),
    renameFile: (path: string, name: string) => post("/api/file/rename", { path, name }),
    deleteFile: (path: string) => transport("/api/file", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  }
}

export const agentRequests = agentApi()

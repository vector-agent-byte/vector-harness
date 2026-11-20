import assert from "node:assert/strict"
import { test } from "node:test"
import { agentApi, fileBytesUrl, readEventStream } from "./src/features/agent/api.ts"
import type { StreamEvent } from "./src/types.ts"

test("agent requests retain session isolation, encoded identifiers and generic mutation bodies", async () => {
  const requests: { url: string; init?: RequestInit }[] = []
  const api = agentApi(async (url, init) => {
    requests.push({ url: String(url), init })
    return new Response("{}")
  })
  await api.listSessions()
  await api.session("folder/session ?")
  await api.createSession()
  await api.setMode("session", "plan")
  await api.setSkills("session", null)
  await api.setSkills("session", [])
  await api.sendMessage("session", "user text")
  await api.stopSession("session")
  await api.deleteSession("session")
  assert.deepEqual(requests.map(request => request.url), [
    "/api/sessions?kind=agent", "/api/sessions/folder%2Fsession%20%3F", "/api/sessions",
    "/api/sessions/session/mode", "/api/sessions/session/skills", "/api/sessions/session/skills",
    "/api/sessions/session/messages", "/api/sessions/session/stop", "/api/sessions/session",
  ])
  assert.equal(requests[0].init?.cache, "no-store")
  assert.equal(requests[1].init?.cache, "no-store")
  assert.deepEqual(requests.slice(2).map(request => request.init?.method), ["POST", "POST", "POST", "POST", "POST", "POST", "DELETE"])
  assert.deepEqual(requests.slice(3, 7).map(request => JSON.parse(String(request.init?.body))), [
    { mode: "plan" }, { names: null }, { names: [] }, { text: "user text" },
  ])
  assert.equal(requests[2].init?.body, undefined)
  assert.equal(requests[7].init?.body, undefined)
})

test("file requests preserve path characters and keep selection separate from browsing", async () => {
  const requests: { url: string; init?: RequestInit }[] = []
  const api = agentApi(async (url, init) => {
    requests.push({ url: String(url), init })
    return new Response("{}")
  })
  const path = "D:/work/中文 #&?.txt"
  await api.dirs("")
  await api.dirs(path)
  await api.file(path)
  await api.setWorkdir(path)
  await api.renameFile(path, "renamed.txt")
  await api.deleteFile(path)
  assert.deepEqual(requests.slice(0, 3).map(request => request.url), [
    "/api/dirs", `/api/dirs?path=${encodeURIComponent(path)}`, `/api/file?path=${encodeURIComponent(path)}`,
  ])
  assert.deepEqual(requests.slice(3).map(request => [request.url, request.init?.method, JSON.parse(String(request.init?.body))]), [
    ["/api/workdir", "POST", { path }], ["/api/file/rename", "POST", { path, name: "renamed.txt" }],
    ["/api/file", "DELETE", { path }],
  ])
  assert.equal(fileBytesUrl(path), `/api/file/bytes?path=${encodeURIComponent(path)}`)
  assert.equal(fileBytesUrl(path, true), `/api/file/bytes?path=${encodeURIComponent(path)}&inline=1`)
})

test("rejected sends remain inspectable and transport failures propagate to rollback handling", async () => {
  const rejected = agentApi(async () => new Response('{"error":"busy"}', { status: 409 }))
  const response = await rejected.sendMessage("session", "text")
  assert.equal(response.status, 409)
  assert.deepEqual(await response.json(), { error: "busy" })
  const offline = agentApi(async () => { throw new TypeError("offline") })
  await assert.rejects(offline.sendMessage("session", "text"), /offline/)
})

test("message streams preserve child routing and completion across network chunks", async () => {
  const frames = [
    { kind: "text_delta", text: "主回复" },
    { kind: "text_delta", text: "child", origin: "child", parent_tool_call_id: "delegate-1" },
    { kind: "run_result", status: "stopped" },
  ]
  const bytes = new TextEncoder().encode(frames.map(frame => `data: ${JSON.stringify(frame)}\n\n`).join(""))
  const api = agentApi(async () => new Response(new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < bytes.length; offset += 7) controller.enqueue(bytes.slice(offset, offset + 7))
      controller.close()
    },
  })))
  const events: StreamEvent[] = []
  const result = await readEventStream(await api.sendMessage("session", "hello"), event => events.push(event))
  assert.deepEqual(events, frames)
  assert.deepEqual(result, { completed: true, status: "stopped" })
})

test("a disconnected stream reports incomplete without resending the user message", async () => {
  let requests = 0
  let delivered = false
  const api = agentApi(async () => {
    requests += 1
    return new Response(new ReadableStream({
      pull(controller) {
        if (delivered) controller.error(new Error("connection lost"))
        else {
          delivered = true
          controller.enqueue(new TextEncoder().encode('data: {"kind":"text_delta","text":"partial"}\n\n'))
        }
      },
    }))
  })
  const events: StreamEvent[] = []
  assert.deepEqual(await readEventStream(await api.sendMessage("session", "hello"), event => events.push(event)), {
    completed: false, status: null,
  })
  assert.equal(events[0]?.text, "partial")
  assert.equal(requests, 1)
})

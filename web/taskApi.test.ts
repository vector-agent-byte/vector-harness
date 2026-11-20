import test from "node:test"
import assert from "node:assert/strict"
import { taskApi, TaskHttpError } from "./src/features/tasks/api.ts"
import { importLegacy } from "./src/features/tasks/legacy.ts"

test("domain requests send configuration and parent identities without browser results", async () => {
  const requests: {url: string; body: unknown}[] = []
  const api = taskApi("autoresearch", async (url, init) => {
    requests.push({url: String(url), body: JSON.parse(String(init?.body ?? "{}"))})
    return Response.json({id: "created", status: "idle", kind: "autoresearch", config: {}})
  })
  await api.create({config: {metric: "RMSE"}, parentSessionId: "parent", parentExperimentId: 0})
  assert.deepEqual(requests, [{url: "/api/autoresearch/tasks", body: {config: {metric: "RMSE"}, parentSessionId: "parent", parentExperimentId: 0}}])
})

test("task run consumes shared SSE snapshots and does not invent terminal status", async () => {
  const events: unknown[] = []
  const api = taskApi("deepresearch", async () => new Response('data: {"kind":"task_snapshot","revision":2,"task":{"id":"task","status":"running"}}\n\n'))
  const result = await api.run("task", event => events.push(event))
  assert.deepEqual(result, {completed: false, status: null})
  assert.equal(events.length, 1)
})

test("legacy import sends identity/config only and cleans only successful items", async () => {
  const records = [{id: "ok", config: {metric: "RMSE"}, score: 900, status: "complete", output: "untrusted"}, {id: "bad", config: {metric: "AUC-ROC"}, output: "keep"}]
  const values = new Map([["vh-modeling-sessions-v1", JSON.stringify(records)]])
  const storage = {getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => {values.set(key, value)}}
  let sent: unknown
  const result = await importLegacy("autoresearch", storage, async (_url, init) => {
    sent = JSON.parse(String(init?.body))
    return Response.json({results: [{id: "ok", status: "imported"}, {id: "bad", status: "invalid", error: "bad config"}]})
  })
  assert.deepEqual(sent, {tasks: records.map(({id, config}) => ({id, kind: "autoresearch", config}))})
  assert.deepEqual(JSON.parse(values.get("vh-modeling-sessions-v1")!), [records[1]])
  assert.ok(result.raw.includes("keep"))
  assert.ok(result.errors.length)
})

test("failed research imports retain raw records and successful IDs clear only their metadata", async () => {
  const values = new Map([["vh-research-ids", '["ok","bad"]'], ["vh-research-meta", '{"ok":{"topic":"one"},"bad":{"topic":"two"}}']])
  const storage = {getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => {values.set(key, value)}}
  await importLegacy("deepresearch", storage, async () => Response.json({results: [{id: "ok", status: "already_imported"}, {id: "bad", status: "not_found"}]}))
  assert.equal(values.get("vh-research-ids"), '["bad"]')
  assert.deepEqual(JSON.parse(values.get("vh-research-meta")!), {bad: {topic: "two"}})
  const before = new Map(values)
  const failed = await importLegacy("deepresearch", storage, async () => {throw new Error("offline")})
  assert.deepEqual(values, before)
  assert.ok(failed.raw.includes("two"))
})

test("server validation messages reach the form unchanged", async () => {
  const api = taskApi("autoresearch", async () => Response.json({error: "invalid_config", message: "timeColumn: required for time split"}, {status: 400}))
  await assert.rejects(api.create({config: {split: "time"}}), /timeColumn: required for time split/)
})

test("missing task details retain HTTP status for deletion recovery", async () => {
  const api = taskApi("deepresearch", async () => Response.json({error: "not_found"}, {status: 404}))
  await assert.rejects(api.detail("deleted"), error => error instanceof TaskHttpError && error.status === 404)
})

test("simultaneous mounts share one legacy import without conflicting cleanup", async () => {
  const values = new Map([["vh-modeling-sessions-v1", '[{"id":"old","config":{}}]']])
  const storage = {getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => {values.set(key, value)}}
  let calls = 0
  const transport: typeof fetch = async () => {calls += 1; return Response.json({results: [{id: "old", status: "imported"}]})}
  const results = await Promise.all([importLegacy("autoresearch", storage, transport), importLegacy("autoresearch", storage, transport)])
  assert.equal(calls, 1)
  assert.deepEqual(results, [{raw: "", errors: []}, {raw: "", errors: []}])
})

test("malformed storage remains exportable without network requests", async () => {
  const storage = {getItem: () => "{broken", setItem: () => assert.fail("must preserve raw data")}
  const result = await importLegacy("autoresearch", storage, async () => {assert.fail("must not send malformed tasks")})
  assert.ok(result.raw.includes("{broken"))
  assert.ok(result.errors.length)
})

test("conflicts and missing import responses retain their records", async () => {
  const records = [{id: "conflict", config: {}}, {id: "missing", config: {}}]
  const storage = {getItem: () => JSON.stringify(records), setItem: () => assert.fail("must preserve unconfirmed records")}
  const result = await importLegacy("autoresearch", storage, async () => Response.json({results: [{id: "conflict", status: "conflict"}, {id: "unrequested", status: "imported"}]}))
  assert.ok(result.raw.includes("missing"))
  assert.ok(result.errors.some(error => error.includes("conflict")))
})

test("records edited while import is pending survive cleanup", async () => {
  let saved = '[{"id":"old","config":{}}]'
  const storage = {getItem: () => saved, setItem: () => assert.fail("must preserve concurrently changed records")}
  const result = await importLegacy("autoresearch", storage, async () => {saved = '[{"id":"old","config":{"name":"edited"}}]'; return Response.json({results: [{id: "old", status: "imported"}]})})
  assert.ok(result.errors.length)
  assert.ok(saved.includes("edited"))
})

test("research metadata without an ID list is imported without inventing an engine", async () => {
  const values = new Map([["vh-research-meta", '{"orphan":{"topic":"server defaults"}}']])
  const storage = {getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => {values.set(key, value)}}
  let sent: unknown
  const result = await importLegacy("deepresearch", storage, async (_url, init) => {
    sent = JSON.parse(String(init?.body))
    return Response.json({results: [{id: "orphan", status: "imported"}]})
  })
  assert.deepEqual(sent, {tasks: [{id: "orphan", kind: "deepresearch", config: {topic: "server defaults"}}]})
  assert.deepEqual(result.errors, [])
  assert.equal(values.get("vh-research-meta"), "{}")
})

import assert from "node:assert/strict"
import { test } from "node:test"

import { MODES, normalizeMode } from "./src/modes.ts"
import { parseSessionList } from "./src/api.ts"

test("all server-provided modes are recognized", () => {
  for (const mode of MODES) {
    assert.equal(normalizeMode(mode.id), mode.id)
  }
})

test("missing or invalid session modes default to ReAct", () => {
  for (const value of [undefined, null, "", "unknown", "SubAgents", {}, 3]) {
    assert.equal(normalizeMode(value), "react")
  }
})

test("reloading the session list preserves independent modes for each session", () => {
  const payload = { running_id: null, sessions: [
    { id: "first", title: "first", mode: "subagents" },
    { id: "second", title: "second", mode: "reflect" },
    { id: "legacy", title: "legacy" },
  ] }
  const sessions = parseSessionList(payload)?.sessions
  assert.deepEqual(sessions?.map(session => session.mode), ["subagents", "reflect", "react"])
  assert.deepEqual(parseSessionList(JSON.parse(JSON.stringify(payload)))?.sessions, sessions)
})

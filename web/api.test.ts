import assert from "node:assert/strict"
import { test } from "node:test"

import { normalizeMessages } from "./src/api.ts"

test("session reload preserves each delegate's child history", () => {
  const messages = normalizeMessages([
    { role: "assistant", tool_calls: [
      { id: "first", name: "delegate", arguments: { task: "first task" }, child: { thinking: "thought", text: "partial", tools: [{ name: "shell", args: { command: "pwd" } }] } },
      { id: "second", name: "delegate", child: { thinking: "second thought", text: "second result", tools: [] } },
    ] },
    { role: "assistant", tool_calls: [{ id: "third", name: "delegate", child: { text: "another round" } }] },
  ])
  assert.deepEqual(messages[0].tool_calls?.[0].child, {
    thinking: "thought", text: "partial", tools: [{ name: "shell", args: { command: "pwd" } }],
  })
  assert.equal(messages[0].tool_calls?.[1].child?.thinking, "second thought")
  assert.equal(messages[1].tool_calls?.[0].child?.text, "another round")
})

test("older sessions and malformed child data remain readable", () => {
  const messages = normalizeMessages([{ tool_calls: [
    { id: "old", name: "delegate" },
    { id: "malformed", name: "delegate", child: { thinking: 3, text: null, tools: [null, {}, { name: "shell", args: 5 }] } },
  ] }])
  assert.equal(messages[0].tool_calls?.[0].child, undefined)
  assert.deepEqual(messages[0].tool_calls?.[1].child, {
    thinking: "", text: "", tools: [{ name: "shell", args: null }],
  })
})

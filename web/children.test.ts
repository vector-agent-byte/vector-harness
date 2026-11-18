import assert from "node:assert/strict"
import { test } from "node:test"
import { updateChildren } from "./src/children.ts"
import { normalizeChild } from "./src/api.ts"
import type { LiveSection, StreamEvent } from "./src/types.ts"

test("interleaved children retain separate output, tools and lifecycle", () => {
  let children: LiveSection[] = []
  const send = (event: StreamEvent) => { children = updateChildren(children, event) }
  for (const id of ["first", "second", "queued"]) {
    send({ kind: "tool_call_end", name: "delegate", tool_call_id: id, arguments: { task: `task ${id}` } })
  }
  for (const id of ["first", "second"]) send({ kind: "tool_execution_start", name: "delegate", tool_call_id: id })
  assert.deepEqual(children.map(child => child.status), ["running", "running", "queued"])
  send({ kind: "thinking_delta", origin: "child", parent_tool_call_id: "first", text: "thought A" })
  send({ kind: "text_delta", origin: "child", parent_tool_call_id: "second", text: "B" })
  send({ kind: "text_delta", origin: "child", parent_tool_call_id: "first", text: "A" })
  send({ kind: "tool_call_end", origin: "child", parent_tool_call_id: "first", tool_call_id: "nested", name: "shell" })
  send({ kind: "run_end", origin: "child", parent_tool_call_id: "second", status: "max_steps" })
  send({ kind: "tool_result", tool_call_id: "second", text: "[max_steps] " })
  assert.equal(children.length, 3)
  assert.equal(children[0].thinking, "thought A")
  assert.equal(children[0].text, "A")
  assert.equal(children[0].tools[0].name, "shell")
  assert.equal(children[0].task, "task first")
  assert.equal(children[0].status, "running")
  assert.equal(children[1].text, "B")
  assert.equal(children[1].status, "max_steps")
  send({ kind: "tool_result", tool_call_id: "first", name: "error" })
  assert.equal(children[0].status, "error")
  assert.equal(children[2].status, "queued")
})

test("unassociated child events never leak into another card", () => {
  const children = updateChildren([], { kind: "tool_execution_start", name: "delegate", tool_call_id: "first" })
  assert.equal(updateChildren(children, { kind: "text_delta", origin: "child", text: "unknown" }), children)
  assert.equal(updateChildren(children, { kind: "tool_result", tool_call_id: "ordinary" }), children)
})

test("reloading preserves valid child lifecycle and tolerates old records", () => {
  assert.equal(normalizeChild({ status: "running" })?.status, "running")
  assert.equal(normalizeChild({ status: "stopped" })?.status, "stopped")
  assert.equal(normalizeChild({ status: "invalid" })?.status, undefined)
  assert.equal(normalizeChild({ text: "old" })?.text, "old")
})

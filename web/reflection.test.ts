import assert from "node:assert/strict"
import { test } from "node:test"

import { lastUserMessageTime, messagePresentation, parseReflection, reflectionInitiallyOpen, reflectionPreview } from "./src/reflection.ts"
import type { ChatMessage } from "./src/types.ts"

function message(role: string, content: string): ChatMessage {
  return { role, content, tool_calls: null, tool_call_id: null, is_error: false, created_at: 123 }
}

test("current Chinese review feedback is an assistant-side review, without mutating history", () => {
  const original = message("user", "反思意见：\n补充测试证据。\n保留日志。")
  assert.deepEqual(messagePresentation(original), {
    role: "assistant", isUser: false, reflection: { pass: false, text: "补充测试证据。\n保留日志。" },
  })
  assert.equal(original.role, "user")
  assert.equal(original.created_at, 123)
})

test("current and legacy verdict markers preserve verdict and markdown", () => {
  for (const marker of ["反思", "Reflection"]) {
    assert.deepEqual(parseReflection(`[${marker}] 通过 — **已核查**`), { pass: true, text: "**已核查**" })
    assert.deepEqual(parseReflection(`[${marker}] 未通过 - 1. 修复\n2. 验证`), { pass: false, text: "1. 修复\n2. 验证" })
  }
  assert.deepEqual(parseReflection("Reflection:\nCheck the files."), { pass: false, text: "Check the files." })
})

test("normal user messages and quoted markers stay on the user side", () => {
  for (const content of ["做一个反思任务", "请解释反思意见：这句话", "> 反思意见：引用", "`[反思] 通过 — 引用`", "[反思] 自定义文字"]) {
    assert.deepEqual(messagePresentation(message("user", content)), { role: "user", isUser: true, reflection: null })
  }
})

test("tool output is never reclassified as a reflection", () => {
  assert.deepEqual(messagePresentation(message("tool", "反思意见：文件内容")), { role: "tool", isUser: false, reflection: null })
})

test("ordinary assistant output stays on the assistant side", () => {
  assert.deepEqual(messagePresentation(message("assistant", "已完成初稿")), { role: "assistant", isUser: false, reflection: null })
})

test("long and multiline reviews start collapsed while short reviews remain visible", () => {
  assert.equal(reflectionInitiallyOpen("简短结论"), true)
  assert.equal(reflectionInitiallyOpen("长".repeat(241)), false)
  assert.equal(reflectionInitiallyOpen("一\n二\n三\n四\n五"), false)
  assert.equal(reflectionInitiallyOpen(""), true)
})

test("collapsed review previews are bounded and do not change the full content", () => {
  assert.equal(reflectionPreview(" 第一条\n\n 第二条 "), "第一条 第二条")
  const text = "完整意见".repeat(100)
  assert.equal(reflectionPreview(text), text.slice(0, 120) + "…")
  assert.equal(text.length, 400)
})

test("live and saved revision timing stays anchored to the actual user request", () => {
  const messages = [
    { ...message("user", "完成任务"), created_at: 10 },
    { ...message("assistant", "初稿"), created_at: 15 },
    { ...message("user", "反思意见：\n补齐验证"), created_at: 20 },
    { ...message("assistant", "修订完成"), created_at: 30 },
  ]
  assert.equal(lastUserMessageTime(messages.slice(0, 3)), 10)
  assert.equal(lastUserMessageTime(messages), 10)
  assert.equal(lastUserMessageTime([...messages, { ...message("user", "下一个任务"), created_at: 40 }]), 40)
  assert.equal(lastUserMessageTime([]), null)
  assert.equal(lastUserMessageTime([{ ...message("user", "旧记录"), created_at: null }]), null)
})

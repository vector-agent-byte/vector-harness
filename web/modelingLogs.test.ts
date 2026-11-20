import test from "node:test"
import assert from "node:assert/strict"
import * as modeling from "./src/modeling.ts"
import {normalizeMessages} from "./src/api.ts"

test("live logs retain their first trigger time as streamed text grows", () => {
    const triggeredAt = Date.UTC(2026, 10, 20, 8, 30, 15)
    let logs = modeling.appendModelLog([], {kind: "thinking_delta", text: "检查"}, triggeredAt)
    logs = modeling.appendModelLog(logs, {kind: "thinking_delta", text: "数据"}, triggeredAt + 2000)
    logs = modeling.appendModelLog(logs, {kind: "tool_call_end", name: "shell"}, triggeredAt + 3000)
    assert.equal(logs[0].createdAt, triggeredAt)
    assert.equal(logs[1].createdAt, triggeredAt + 3000)
    assert.equal(JSON.parse(JSON.stringify(logs))[0].createdAt, triggeredAt)
    const before = Date.now()
    const live = modeling.appendModelLog([], {kind: "text_delta", text: "实时输出"})
    assert.ok(live[0].createdAt! >= before && live[0].createdAt! <= Date.now())
})

test("restored logs use persisted message timestamps without inventing missing times", () => {
    const logs = modeling.modelLogsFromMessages(normalizeMessages([
        {role: "assistant", content: "检查数据", created_at: 1795163415.5, tool_calls: [{id: "tool-1", name: "shell", arguments: {command: "python train.py"}, child: {text: "子任务输出"}}]},
        {role: "tool", tool_call_id: "tool-1", content: "训练完成", created_at: 1795163418},
        {role: "assistant", content: "旧记录"},
    ]))
    assert.deepEqual(logs.map(log => log.createdAt), [1795163415500, 1795163415500, null, 1795163418000, null])
})

test("log summaries show commands and readable todo progress", () => {
    const command = modeling.describeModelLog({kind: "tool_call_end", label: "调用工具 · shell", source: "main", content: JSON.stringify({command: "python train.py", timeout: 60})})
    assert.equal(command.preview, "python train.py")
    assert.match(command.content, /timeout/)
    const todos = modeling.describeModelLog({kind: "tool_call_end", label: "调用工具 · update_todos", source: "main", content: JSON.stringify({todos: [
        {id: 1, content: "检查数据", status: "completed"},
        {id: 2, content: "训练模型", status: "in_progress"},
        {id: 3, content: "评估模型", status: "pending"},
        null,
    ]})})
    assert.match(todos.preview, /1\/3/)
    assert.match(todos.preview, /训练模型/)
    assert.equal(todos.todos.length, 3)
    assert.equal(todos.todos[1].status, "in_progress")
})

test("log summaries keep full details and handle malformed parameters", () => {
    const content = "训练结果\n" + "内容".repeat(200)
    const result = modeling.describeModelLog({kind: "tool_result", label: "执行结果", source: "main", content})
    assert.ok(result.preview.length <= 160)
    assert.equal(result.content, content)
    const malformed = modeling.describeModelLog({kind: "tool_call_end", label: "调用工具", source: "main", content: "{invalid"})
    assert.equal(malformed.preview, "{invalid")
    assert.deepEqual(malformed.todos, [])
    const report = modeling.describeModelLog({kind: "text_delta", label: "输出", source: "main", content: '评估完成\n```modeling-report\n{"experiments": []}\n```'})
    assert.doesNotMatch(report.content, /"experiments"/)
    assert.match(report.content, /实验详情/)
})

test("execution logs show thinking and tools before any assistant text", () => {
    let logs = modeling.appendModelLog([], {kind: "thinking_delta", text: "检查数据"})
    logs = modeling.appendModelLog(logs, {kind: "thinking_delta", text: "并训练"})
    logs = modeling.appendModelLog(logs, {kind: "tool_call_end", name: "shell", tool_call_id: "train-1", arguments: {command: "python train.py"}})
    logs = modeling.appendModelLog(logs, {kind: "tool_execution_start", name: "shell"})
    logs = modeling.appendModelLog(logs, {kind: "tool_result", name: "", tool_call_id: "train-1", text: "AUC: 0.81"})
    assert.equal(logs[0].content, "检查数据并训练")
    assert.ok(logs.some(log => log.content.includes("python train.py")))
    assert.ok(logs.some(log => log.label.includes("执行中")))
    assert.ok(logs.some(log => log.content.includes("AUC: 0.81")))
    assert.match(logs.at(-1)!.label, /shell/)
})

test("child output stays separate and failed tools remain visible", () => {
    let logs = modeling.appendModelLog([], {kind: "text_delta", text: "主任务"})
    logs = modeling.appendModelLog(logs, {kind: "text_delta", origin: "child", parent_tool_call_id: "child-1", text: "子任务"})
    logs = modeling.appendModelLog(logs, {kind: "text_delta", origin: "child", parent_tool_call_id: "child-2", text: "另一子任务"})
    logs = modeling.appendModelLog(logs, {kind: "tool_result", name: "error", text: "训练失败"})
    assert.equal(logs.length, 4)
    assert.match(logs[1].label, /子任务/)
    assert.match(logs[3].label, /失败/)
    assert.equal(logs[3].content, "训练失败")
    assert.deepEqual(modeling.appendModelLog(logs, {kind: "text_delta", text: "  "}), logs)
    assert.deepEqual(modeling.appendModelLog(logs, {kind: "run_end"}), logs)
})

test("history restores tool calls and results even without assistant prose", () => {
    const logs = modeling.modelLogsFromMessages(normalizeMessages([
        {role: "user", content: "private task prompt"},
        {role: "assistant", content: "", tool_calls: [{id: "tool-1", name: "shell", arguments: {command: "python train.py"}}]},
        {role: "tool", tool_call_id: "tool-1", content: "训练失败", is_error: true},
        {role: "assistant", content: "最终报告"},
    ]))
    assert.equal(logs.length, 3)
    assert.match(logs[0].content, /python train.py/)
    assert.match(logs[1].label, /shell.*失败/)
    assert.equal(logs[1].content, "训练失败")
    assert.equal(logs[2].content, "最终报告")
    assert.ok(logs.every(log => !log.content.includes("private task prompt")))
})

import test from "node:test"
import assert from "node:assert/strict"
import {defaultModelConfig} from "./src/features/autoresearch/config.ts"
import type {ModelOptions} from "./src/features/autoresearch/types.ts"
import {fieldChoices, fieldInputProps, taskDraft, applyServerDefaults} from "./src/features/autoresearch/options.ts"

const options: ModelOptions = {
  defaults: {...defaultModelConfig, task: "server-task", metric: "server-metric", threshold: 9, maxSteps: 71},
  fields: {
    metric: {type: "string", enumByTask: {"server-task": ["first-metric", "second-metric"]}},
    threshold: {type: "number", minimum: -10, maximumByMetric: {"first-metric": 22}, defaultByTask: {"server-task": 12}},
    maxSteps: {type: "integer", minimum: 7, maximum: 83},
    hours: {type: "number", minimum: 0.25, maximum: 9.5},
    timeColumn: {type: "string", requiredWhen: {split: "server-split"}},
    algorithms: {type: "array", items: {type: "string", enum: ["server-algorithm"]}},
  },
  enums: {task: ["server-task"], metric: ["server-metric"], split: ["server-split"], strategy: ["server-strategy"], algorithms: ["enum-algorithm"]},
}

test("form choices and task-switch defaults are supplied entirely by metadata", () => {
  const draft = taskDraft(defaultModelConfig, "server-task", options)
  assert.equal(draft.metric, "first-metric")
  assert.equal(draft.threshold, 12)
  assert.deepEqual(fieldChoices(options, "metric", draft), ["first-metric", "second-metric"])
  assert.deepEqual(fieldChoices(options, "task", draft), ["server-task"])
  assert.deepEqual(fieldChoices(options, "split", draft), ["server-split"])
  assert.deepEqual(fieldChoices(options, "strategy", draft), ["server-strategy"])
  assert.deepEqual(fieldChoices(options, "algorithms", draft), ["server-algorithm"])
})

test("input ranges, metric-specific maxima, and conditional required state follow metadata", () => {
  const draft = taskDraft(defaultModelConfig, "server-task", options)
  const threshold = fieldInputProps(options, "threshold", draft)
  assert.equal(threshold.min, -10)
  assert.equal(threshold.max, 22)
  assert.equal(threshold.step, "any")
  assert.equal(fieldInputProps(options, "maxSteps", draft).max, 83)
  assert.equal(fieldInputProps(options, "maxSteps", draft).step, 1)
  assert.equal(fieldInputProps(options, "hours", draft).max, 9.5)
  assert.equal(fieldInputProps(options, "timeColumn", {...draft, split: "server-split"}).required, true)
  assert.equal(fieldInputProps(options, "timeColumn", draft).required, false)
  assert.equal(fieldInputProps(options, "threshold", {...draft, metric: "unbounded"}).max, undefined)
})

test("late options preserve edited drafts while replacing untouched placeholder policy", () => {
  const draft = {...defaultModelConfig, description: "user draft"}
  const hydrated = applyServerDefaults(draft, options.defaults, new Set(["description"]))
  assert.equal(hydrated.description, "user draft")
  assert.equal(hydrated.maxSteps, 71)
  assert.equal(hydrated.metric, "server-metric")
  assert.deepEqual(fieldChoices(null, "algorithms", draft), [])
})

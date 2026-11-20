import test from "node:test"
import assert from "node:assert/strict"
import { defaultModelConfig, validateModelConfig, buildModelPrompt, parseModelReport, bestExperiment } from "./src/modeling.ts"

test("configuration requires data, target and meaningful budgets", () => {
  assert.match(validateModelConfig(defaultModelConfig) ?? "", /数据/)
  const config = { ...defaultModelConfig, dataPath: "data.csv", target: "label", description: "预测风险" }
  assert.equal(validateModelConfig(config), null)
  assert.ok(validateModelConfig({ ...config, testRatio: 100 }))
  assert.ok(validateModelConfig({ ...config, maxSteps: 0 }))
  assert.ok(validateModelConfig({ ...config, maxSteps: 1.5 }))
  assert.ok(validateModelConfig({ ...config, split: "time", timeColumn: "" }))
})

test("prompt carries configuration and prevents test-set optimization", () => {
  const prompt = buildModelPrompt({ ...defaultModelConfig, dataPath: "train.csv", target: "label", metric: "RMSE" })
  assert.match(prompt, /train.csv/)
  assert.match(prompt, /RMSE/)
  assert.match(prompt, /测试集.*最终/)
  assert.match(prompt, /modeling-report/)
})

test("only explicit reports with finite numeric metrics are accepted", () => {
  assert.deepEqual(parseModelReport("AUC 0.93"), [])
  assert.deepEqual(parseModelReport('```modeling-report\ninvalid\n```'), [])
  const report = '```modeling-report\n' + JSON.stringify({ experiments: [
    { id: 0, title: "基线", score: 0.7 },
    { id: 1, title: "改进", score: 0.8 },
    { id: 2, title: "坏数据", score: "0.9" },
  ] }) + '\n```'
  assert.equal(parseModelReport(report).length, 2)
  assert.equal(bestExperiment(parseModelReport(report), "AUC-ROC")?.id, 1)
  assert.equal(bestExperiment(parseModelReport(report), "RMSE")?.id, 0)
})

test("duplicate experiments use the latest report and empty results stay empty", () => {
  const block = (score: number) => '```modeling-report\n' + JSON.stringify({ experiments: [{ id: 0, title: "基线", score }] }) + '\n```'
  assert.equal(parseModelReport(block(0.6) + block(0.7)).length, 1)
  assert.equal(parseModelReport(block(0.6) + block(0.7))[0].score, 0.7)
  assert.equal(bestExperiment([], "AUC-ROC"), undefined)
})

import test from "node:test"
import assert from "node:assert/strict"
import {readFileSync, readdirSync} from "node:fs"
import {join} from "node:path"
import {fileURLToPath} from "node:url"
import {taskApi} from "./src/features/tasks/api.ts"

test("task projections retain backend identities and flags despite contradictory scores", async () => {
  const task = {id: "server", kind: "autoresearch", config: {}, status: "completed", updated_at: 123, baselineId: 8, bestId: 9, improvement: -2, metricDirection: "minimize", experiments: [{id: 8, score: 1, improved: false}, {id: 9, score: 3, improved: true}]}
  const api = taskApi("autoresearch", async () => Response.json({task, messages: [], warnings: ["partial report"]}))
  assert.deepEqual((await api.detail("server")).task, task)
})

test("production frontend contains no domain prompt builders or result inference", () => {
  const root = fileURLToPath(new URL("./src", import.meta.url))
  const files = (directory: string): string[] => readdirSync(directory, {withFileTypes: true}).flatMap(entry => entry.isDirectory() ? files(join(directory, entry.name)) : /\.[tj]sx?$/.test(entry.name) ? [join(directory, entry.name)] : [])
  for (const file of files(root).filter(file => !file.endsWith("demo.ts"))) {
    const source = readFileSync(file, "utf8")
    assert.doesNotMatch(source, /buildModelPrompt|buildResearchPrompt|parseModelReport|bestExperiment|lowerIsBetter|extractResearchTasks|extractResearchTopic|extractTaskDetail/, file)
  }
})

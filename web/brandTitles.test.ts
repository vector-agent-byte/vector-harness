import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"

for (const [file, english, chinese] of [
  ["App.tsx", "harness", "智能体"],
  ["DeepResearch.tsx", "deep-research", "深度研究"],
  ["SelfModeling.tsx", "auto-research", "自进化建模"],
]) {
  test(`${english} is the primary brand title with a Chinese annotation`, () => {
    const source = readFileSync(new URL(`./src/${file}`, import.meta.url), "utf8")
    assert.match(source, new RegExp(`<strong>${english}</strong>\\s*<small>${chinese}</small>`))
  })
}

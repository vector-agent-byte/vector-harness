import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"

const stylesheet = readFileSync(new URL("./src/App.css", import.meta.url), "utf8")

function declarations(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  const match = stylesheet.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))
  assert.ok(match, `Missing style rule: ${selector}`)
  return match[1]
}

test("completed plan items remain readable without a strike-through", () => {
  const completed = declarations(".plan-item.completed .plan-content")
  assert.match(completed, /text-decoration:\s*none\s*;/)
  assert.doesNotMatch(completed, /line-through/)
})

test("long plan descriptions wrap within their row", () => {
  const content = declarations(".plan-content")
  assert.match(content, /min-width:\s*0\s*;/)
  assert.match(content, /overflow-wrap:\s*anywhere\s*;/)
})

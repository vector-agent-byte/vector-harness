import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"

for (const [file, english, chinese] of [
  ["features/agent/AgentSidebar.tsx", "harness", "智能体"],
  ["features/deepresearch/DeepResearchPage.tsx", "deep-research", "深度研究"],
  ["features/autoresearch/AutoresearchPage.tsx", "auto-research", "自进化建模"],
]) {
  test(`${english} is the primary brand title with a Chinese annotation`, () => {
    const source = readFileSync(new URL(`./src/${file}`, import.meta.url), "utf8")
    assert.match(source, new RegExp(`<strong>${english}</strong>\\s*<small>${chinese}</small>`))
  })
}

test("deep-research uses a green title and line icon with a muted annotation", () => {
  const stylesheet = readFileSync(new URL("./src/App.css", import.meta.url), "utf8")
  const source = readFileSync(new URL("./src/features/deepresearch/DeepResearchPage.tsx", import.meta.url), "utf8")

  for (const selector of ["research-title-name strong", "research-title-icon"]) {
    assert.match(stylesheet, new RegExp(`(?:^|})\\s*\\.${selector}\\s*\\{[^}]*color:\\s*#166534\\s*;`, "i"))
  }
  assert.match(stylesheet, /(?:^|})\s*\.research-title-name small\s*\{[^}]*color:\s*#6b7280\s*;/i)
  assert.match(source, /<svg\s[^>]*className="research-title-icon"[^>]*stroke="currentColor"[^>]*aria-hidden="true"[^>]*>/)
  assert.doesNotMatch(source, /<span className="research-title-icon">🔍<\/span>/)
})

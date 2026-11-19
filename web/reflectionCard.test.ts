import assert from "node:assert/strict"
import { after, before, test } from "node:test"
import { createElement } from "react"
import type { ComponentType } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { createServer } from "vite"
import type { ViteDevServer } from "vite"

let server: ViteDevServer | undefined
let ReflectionCard: ComponentType<{ pass: boolean; text: string }>

before(async () => {
  server = await createServer({ server: { middlewareMode: true }, appType: "custom" })
  ReflectionCard = (await server.ssrLoadModule("/src/components.tsx")).ReflectionCard
})

after(async () => {
  await server?.close()
})

test("long feedback renders as a collapsed review with preview and full markdown", () => {
  const text = "需要补齐证据。".repeat(50) + "\n\n**验证结果**"
  const html = renderToStaticMarkup(createElement(ReflectionCard, { pass: false, text }))
  assert.match(html, /^<details class="reflection-card needs-work">/)
  assert.match(html, /<summary class="reflection-summary">/)
  assert.match(html, /反思审查/)
  assert.match(html, /需改进/)
  assert.match(html, /class="reflection-preview"/)
  assert.match(html, /<strong>验证结果<\/strong>/)
  assert.doesNotMatch(html, /反思未通过|class="fail"/)
})

test("a short successful review is expanded and does not show failure wording", () => {
  const html = renderToStaticMarkup(createElement(ReflectionCard, { pass: true, text: "已完成核查。" }))
  assert.match(html, /^<details class="reflection-card pass" open="">/)
  assert.match(html, /<span class="reflection-verdict">通过<\/span>/)
  assert.match(html, /已完成核查。/)
  assert.doesNotMatch(html, /需改进/)
})

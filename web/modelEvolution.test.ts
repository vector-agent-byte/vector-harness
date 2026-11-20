import assert from "node:assert/strict"
import { after, before, test } from "node:test"
import { createElement } from "react"
import type { ComponentType } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { createServer } from "vite"
import type { ViteDevServer } from "vite"
import type { Experiment } from "./src/modeling.ts"
import { demoExperiments } from "./src/modeling.ts"

let server: ViteDevServer
let Chart: ComponentType<{ experiments: Experiment[]; metric: string; onSelect: (id: number) => void }>
before(async () => {
  server = await createServer({ server: { middlewareMode: true }, appType: "custom" })
  Chart = (await server.ssrLoadModule("/src/ModelEvolution.tsx")).default
})
after(async () => { await server?.close() })

test("chart uses bounded height, readable summary and accessible experiment controls", () => {
  const html = renderToStaticMarkup(createElement(Chart, { experiments: demoExperiments, metric: "AUC-ROC", onSelect() {} }))
  assert.match(html, /height="280"/)
  assert.match(html, /指标演进/)
  assert.match(html, /较基线改善/)
  assert.match(html, /查看实验/)
  assert.match(html, /vector-effect="non-scaling-stroke"/)
  assert.equal((html.match(/role="button"/g) ?? []).length, demoExperiments.length)
})

test("empty and single-experiment results render without invalid chart coordinates", () => {
  const empty = renderToStaticMarkup(createElement(Chart, { experiments: [], metric: "RMSE", onSelect() {} }))
  assert.match(empty, /尚无可用/)
  const single = renderToStaticMarkup(createElement(Chart, { experiments: demoExperiments.slice(0, 1), metric: "RMSE", onSelect() {} }))
  assert.doesNotMatch(single, /NaN|Infinity/)
  assert.match(single, /越低越好/)
})

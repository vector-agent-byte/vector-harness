import assert from "node:assert/strict"
import { test } from "node:test"

import { findListableDir, shouldShowPicker } from "./src/dirPath.ts"

test("picker still opens when the saved directory has no listing", () => {
  assert.equal(shouldShowPicker(true, false), true)
  assert.equal(shouldShowPicker(false, true), false)
})

test("a deleted directory falls back to the nearest existing parent", async () => {
  const gone = "D:\\CODE_WORKSPACE\\CURSOR\\vector-agent\\vector-harness\\demo"
  const parent = "D:\\CODE_WORKSPACE\\CURSOR\\vector-agent\\vector-harness"
  const asked: string[] = []
  const found = await findListableDir(gone, async (path) => {
    asked.push(path)
    return path === parent
  })
  assert.deepEqual(found, { path: parent, relocated: true })
  assert.deepEqual(asked, [gone, parent])
})

test("an existing directory stays put", async () => {
  const path = "D:\\work"
  const found = await findListableDir(path, async () => true)
  assert.deepEqual(found, { path, relocated: false })
})

test("walking stops at a missing drive root", async () => {
  const asked: string[] = []
  const found = await findListableDir("D:\\gone", async (path) => {
    asked.push(path)
    return false
  })
  assert.equal(found, null)
  assert.deepEqual(asked, ["D:\\gone", "D:\\"])
})

test("a late listing does not replace another folder, and an open picker keeps its draft", async () => {
  const { listingIsCurrent, refreshMayReplaceDraft, REFRESH_MS } = await import("./src/dirPath.ts")
  assert.equal(listingIsCurrent("D:\\a", "D:\\a"), true)
  assert.equal(listingIsCurrent("D:\\a", "D:\\b"), false)
  assert.equal(refreshMayReplaceDraft(true), false)
  assert.equal(refreshMayReplaceDraft(false), true)
  assert.equal(REFRESH_MS, 3000)
})

test("file and directory context menus stay distinct", async () => {
  const { entryMenu } = await import("./src/dirPath.ts")
  assert.deepEqual(entryMenu("file"), ["查看", "重命名", "下载", "删除"])
  assert.deepEqual(entryMenu("dir"), ["重命名", "删除"])
})

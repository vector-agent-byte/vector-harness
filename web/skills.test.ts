import assert from "node:assert/strict"
import { test } from "node:test"

import { parseSessionList } from "./src/api.ts"
import { sessionSkillSelection, skillSelectionLabel, toggleSkill } from "./src/skills.ts"

test("all, none and multiple selections remain distinct after reload", () => {
  const payload = { running_id: null, sessions: [
    { id: "all", title: "all", skills: null },
    { id: "some", title: "some", skills: ["alpha", "beta"] },
    { id: "none", title: "none", skills: [] },
  ] }
  assert.deepEqual(parseSessionList(payload)?.sessions.map(session => session.skills), [null, ["alpha", "beta"], []])
  assert.deepEqual(parseSessionList(JSON.parse(JSON.stringify(payload))), parseSessionList(payload))
})

test("legacy single skill selections and default-all sessions are supported", () => {
  assert.deepEqual(sessionSkillSelection({ skill: "alpha" }), ["alpha"])
  assert.equal(sessionSkillSelection({}), null)
  assert.equal(sessionSkillSelection({ skills: null, skill: "alpha" }), null)
  assert.deepEqual(sessionSkillSelection({ skills: [] }), [])
})

test("invalid data fails closed and duplicate names are removed", () => {
  assert.deepEqual(sessionSkillSelection({ skills: "alpha" }), [])
  assert.deepEqual(sessionSkillSelection({ skills: ["alpha", "alpha", null, ""] }), ["alpha"])
})

test("unchecking one skill from all retains the other selected skills", () => {
  const selected = toggleSkill(null, "beta", ["alpha", "beta", "gamma"])
  assert.deepEqual(selected, ["alpha", "gamma"])
  assert.deepEqual(toggleSkill(selected, "beta", []), ["alpha", "gamma", "beta"])
  assert.deepEqual(selected, ["alpha", "gamma"])
  assert.deepEqual(toggleSkill([], "alpha", []), ["alpha"])
})

test("selection labels distinguish all, none and partial selections", () => {
  assert.equal(skillSelectionLabel(null), "全部技能")
  assert.equal(skillSelectionLabel([]), "不使用技能")
  assert.equal(skillSelectionLabel(["alpha"]), "alpha")
  assert.equal(skillSelectionLabel(["alpha", "beta"]), "已选 2 项技能")
})

import test from "node:test"
import assert from "node:assert/strict"
import {normalizeAppView} from "./src/appViews.ts"

test("first visits and unknown saved views open the homepage", () => {
    for (const value of [null, undefined, "", "unknown", {}, 1]) {
        assert.equal(normalizeAppView(value), "home")
    }
})

test("restoring a workspace keeps the user's selected view", () => {
    for (const value of ["home", "agent", "deepresearch", "modeling"] as const) {
        assert.equal(normalizeAppView(value), value)
    }
})

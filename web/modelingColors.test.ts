import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"

const stylesheet = readFileSync(new URL("./src/SelfModeling.css", import.meta.url), "utf8")

function luminance(hex: string): number {
  const channels = hex.match(/[a-f\d]{2}/gi)!.map(channel => {
    const value = parseInt(channel, 16) / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}

function contrast(first: string, second: string): number {
  const values = [luminance(first), luminance(second)].sort((left, right) => right - left)
  return (values[0] + 0.05) / (values[1] + 0.05)
}

test("modeling text palette maintains readable contrast on workspace surfaces", () => {
  for (const token of ["ink", "text", "muted", "blue", "green"]) {
    const match = stylesheet.match(new RegExp(`--model-${token}:\\s*(#[a-f\\d]{6})`, "i"))
    assert.ok(match, `Missing color token: ${token}`)
    for (const background of ["#ffffff", "#f0f4fa", "#e5eefb"]) {
      assert.ok(contrast(match[1], background) >= 4.5, `${token} must reach 4.5:1 on ${background}`)
    }
  }
})

test("primary action and best-result badges maintain readable contrast", () => {
  assert.ok(contrast("#ffffff", "#245dc6") >= 4.5)
  assert.ok(contrast("#08785d", "#def3e9") >= 4.5)
})

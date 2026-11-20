/** Real browser -> HTTP -> scripted provider smoke. Build web first, then run
 * PYTHON_PATH=/path/to/python CHROME_PATH=/path/to/chrome node web/backend.browser.mjs.
 * Requires Node with native WebSocket; no browser automation dependencies.
 */
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { once } from "node:events"
import { access, mkdtemp, readFile, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { basename, delimiter, dirname, join, resolve } from "node:path"
import { createInterface } from "node:readline"
import { fileURLToPath } from "node:url"

const root = fileURLToPath(new URL("../", import.meta.url))
const profileRoot = resolve(tmpdir())
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))
const timeout = Number(process.env.BROWSER_TIMEOUT_MS || 20000)
const python = process.env.PYTHON_PATH || (process.platform === "win32" ? "python" : "python3")
const chrome = process.env.CHROME_PATH || (process.platform === "win32"
  ? "C:/Program Files/Google/Chrome/Application/chrome.exe"
  : process.platform === "darwin" ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : "google-chrome")
const providerCalls = []
const exceptions = []
const apiFailures = []
const responses = []
const networkRequests = new Map()
const pending = new Map()
let sequence = 0
let socket
let browser
let fixture
let profile
let ready
let stopped
let processError
let serverLog = ""
let browserLog = ""
let base

async function waitUntil(check, description) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (processError) throw processError
    const result = await check()
    if (result) return result
    await delay(100)
  }
  throw new Error(`Timed out waiting for ${description}`)
}

function launch(command, args, options) {
  const child = spawn(command, args, { windowsHide: true, ...options })
  child.on("error", error => { processError = error })
  return child
}

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence
    const timer = setTimeout(() => {
      pending.delete(id)
      reject(new Error(`CDP timeout: ${method}`))
    }, timeout)
    pending.set(id, { resolve, reject, timer })
    socket.send(JSON.stringify({ id, method, params }))
  })
}

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text)
  return result.result?.value
}

const waitFor = expression => waitUntil(() => evaluate(expression), expression)

async function click(selector, text) {
  await waitFor(`Array.from(document.querySelectorAll(${JSON.stringify(selector)})).some(element => element.getClientRects().length && !element.disabled && (${JSON.stringify(text ?? null)} === null || element.textContent.includes(${JSON.stringify(text ?? "")})))`)
  await evaluate(`(() => {
    const element = Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(element => element.getClientRects().length && !element.disabled && (${JSON.stringify(text ?? null)} === null || element.textContent.includes(${JSON.stringify(text ?? "")})));
    element.click();
  })()`)
}

async function fill(selector, value) {
  await waitFor(`!!document.querySelector(${JSON.stringify(selector)})`)
  await evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`)
}

async function get(path) {
  const response = await fetch(base + path)
  assert.equal(response.status, 200, `GET ${path}`)
  return response.json()
}

async function taskComplete(kind, name) {
  return waitUntil(async () => {
    const { tasks } = await get(`/api/${kind}/tasks`)
    const task = tasks.find(task => task.topic === name || task.config.name === name)
    assert.notEqual(task?.status, "error", `${kind} failed`)
    return task?.status === "completed" && task
  }, `${kind} persisted completion`)
}

async function navigate(view) {
  await click(`.activity-nav button[aria-label='${view}']`)
}

async function reload() {
  await send("Page.reload", { ignoreCache: true })
  await waitFor("document.readyState === 'complete' && !!document.querySelector('.activity-nav')")
}

async function stopChild(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return
  const exited = once(child, "exit")
  child.kill()
  await Promise.race([exited, delay(3000)])
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL")
    await Promise.race([exited, delay(3000)])
  }
}

try {
  await access(join(root, "web", "dist", "index.html"))
  fixture = launch(python, ["-u", join(root, "tests", "browser_fixture.py")], {
    cwd: root,
    env: { ...process.env, PYTHONPATH: [join(root, "src"), process.env.PYTHONPATH].filter(Boolean).join(delimiter), PYTHONDONTWRITEBYTECODE: "1" },
    stdio: ["pipe", "pipe", "pipe"],
  })
  fixture.stderr.on("data", chunk => { serverLog += chunk })
  createInterface({ input: fixture.stdout }).on("line", line => {
    try {
      const event = JSON.parse(line)
      if (event.event === "ready") ready = event
      if (event.event === "stopped") stopped = event
      if (event.event === "provider") providerCalls.push(event.kind)
    } catch { serverLog += line + "\n" }
  })
  await waitUntil(() => {
    assert.equal(fixture.exitCode, null, `Fixture exited: ${serverLog}`)
    return ready
  }, "fixture readiness")
  base = `http://127.0.0.1:${ready.port}`
  profile = await mkdtemp(join(profileRoot, "vector-backend-browser-"))
  browser = launch(chrome, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] })
  browser.stderr.on("data", chunk => { browserLog += chunk })
  const port = await waitUntil(async () => {
    try { return Number((await readFile(join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]) }
    catch (error) { if (error.code !== "ENOENT") throw error }
  }, "Chrome debugging port")
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json()
  socket = new WebSocket(targets.find(target => target.type === "page").webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
  socket.onmessage = event => {
    const message = JSON.parse(event.data)
    if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails)
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") exceptions.push(message.params.args)
    if (message.method === "Network.requestWillBeSent") networkRequests.set(message.params.requestId, message.params.request)
    if (message.method === "Network.responseReceived") {
      const { response, requestId } = message.params
      if (response.url.startsWith(base + "/api/")) {
        const record = { path: new URL(response.url).pathname, status: response.status, method: networkRequests.get(requestId)?.method }
        responses.push(record)
        if (response.status >= 400) apiFailures.push(record)
      }
    }
    if (message.method === "Network.loadingFailed") {
      const request = networkRequests.get(message.params.requestId)
      if (request?.url.startsWith(base + "/api/") && !message.params.canceled) apiFailures.push({ url: request.url, error: message.params.errorText })
    }
    if (pending.has(message.id)) {
      const request = pending.get(message.id)
      clearTimeout(request.timer)
      pending.delete(message.id)
      if (message.error) request.reject(new Error(JSON.stringify(message.error)))
      else request.resolve(message.result)
    }
  }
  await send("Runtime.enable")
  await send("Page.enable")
  await send("Network.enable")
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false })
  await send("Page.navigate", { url: base })

  await navigate("深度研究")
  await fill(".research-topic-input", "Browser research smoke")
  await click(".research-form button[type='submit']")
  const research = await taskComplete("deepresearch", "Browser research smoke")
  await waitFor("document.querySelector('.research-app')?.textContent.includes('Browser research complete')")
  assert.match((await get(`/api/deepresearch/tasks/${research.id}`)).task.report, /Browser research complete/)
  await reload()
  await navigate("深度研究")
  await click(".research-history-item", "Browser research smoke")
  await waitFor("document.querySelector('.research-app')?.textContent.includes('Browser research complete')")
  console.log("PASS research: UI create/run, real streamed report, persisted history and report after reload")

  await navigate("自进化建模")
  await click(".model-new")
  await waitUntil(() => responses.some(response => response.path === "/api/autoresearch/options" && response.status === 200), "browser receives backend options")
  await waitFor("!!document.querySelector('.model-primary:not(:disabled)')")
  const options = await get("/api/autoresearch/options")
  const choices = await evaluate("Array.from(document.querySelectorAll('.model-field select')[0].options, option => option.value)")
  assert.deepEqual(choices, options.enums.task)
  await fill("input[placeholder='选填，留空自动命名']", "Browser modeling smoke")
  await fill(".model-field textarea", "Deterministic browser integration fixture")
  await fill("input[placeholder='data/train.csv']", "data/train.csv")
  await fill("input[placeholder='如 default_flag']", "target")
  await click(".model-primary")
  const modeling = await taskComplete("autoresearch", "Browser modeling smoke")
  const detail = (await get(`/api/autoresearch/tasks/${modeling.id}`)).task
  assert.equal(detail.bestId, 1)
  assert.equal(detail.experiments.length, 2)
  assert.equal(detail.experiments[1].score, 0.89)
  await waitFor("document.querySelector('.model-score')?.textContent.includes('0.89000')")
  await reload()
  await navigate("自进化建模")
  await click(".model-history-item", "Browser modeling smoke")
  await waitFor("document.querySelector('.model-score')?.textContent.includes('0.89000')")
  await waitFor("document.querySelector('.model-app')?.textContent.includes('Browser best')")
  console.log("PASS modeling: backend options, required form, real report projection, best score and persisted reload")

  await navigate("智能体")
  await click(".new-session")
  await fill(".composer textarea", "Browser agent smoke")
  await click(".composer button[type='submit']")
  await waitFor("document.body.innerText.includes('Browser agent complete')")
  await waitUntil(async () => !(await get("/api/sessions")).running_id, "agent completion")
  console.log("PASS agent: UI session creation and real streamed chat reply")

  for (const kind of ["deepresearch", "autoresearch"]) {
    assert(responses.some(response => response.path === `/api/${kind}/tasks` && response.method === "POST" && response.status === 201), `${kind} browser create request`)
    assert(responses.some(response => response.path.startsWith(`/api/${kind}/tasks/`) && response.path.endsWith("/run") && response.method === "POST" && response.status === 200), `${kind} browser run request`)
  }
  assert.deepEqual(providerCalls, ["deepresearch", "autoresearch", "agent"])
  assert.deepEqual(exceptions, [], "Browser runtime/console errors")
  assert.deepEqual(apiFailures, [], "Failed browser API requests")
  console.log(`PASS transport: ${responses.length} browser API responses, 3 scripted provider calls, 0 browser exceptions, 0 failed API calls`)
} catch (error) {
  if (socket?.readyState === WebSocket.OPEN) {
    try { console.error("Visible page:", await evaluate("document.body.innerText")) } catch {}
  }
  console.error("Fixture stderr:", serverLog, "\nChrome stderr:", browserLog)
  throw error
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    try { await send("Browser.close") } catch {}
    socket.close()
  }
  await stopChild(browser)
  for (const request of pending.values()) {
    clearTimeout(request.timer)
    request.reject(new Error("Browser closed"))
  }
  pending.clear()
  if (fixture?.exitCode === null) {
    fixture.stdin.end("shutdown\n")
    await Promise.race([once(fixture, "exit"), delay(5000)])
  }
  await stopChild(fixture)
  if (profile) {
    const target = resolve(profile)
    assert.equal(dirname(target), profileRoot, "Browser cleanup must remain inside its temporary directory")
    assert.ok(basename(target).startsWith("vector-backend-browser-"), "Browser cleanup must target its own profile")
    await rm(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
  }
  if (ready) {
    assert.equal(stopped?.workspace_removed, true, "Fixture must shut down and remove its temporary workspace")
    assert.equal(fixture.exitCode, 0, "Fixture clean exit")
    console.log("PASS cleanup: fixture stopped, temporary workspace and browser profile removed")
  }
}

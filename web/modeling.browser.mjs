import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { mkdir, mkdtemp, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"

const profile = await mkdtemp(join(tmpdir(), "vector-modeling-browser-"))
const outputDir = join(tmpdir(), "vector-modeling-preview")
await mkdir(outputDir, { recursive: true })
const chrome = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe"
const browser = spawn(chrome, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=9338", `--user-data-dir=${profile}`, "about:blank"], { windowsHide: true, stdio: "ignore" })
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))
let socket
let sequence = 0
const requests = new Map()
const errors = []
async function connect() {
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      const targets = await (await fetch("http://127.0.0.1:9338/json")).json()
      const target = targets.find(item => item.type === "page")
      if (target) {
        socket = new WebSocket(target.webSocketDebuggerUrl)
        await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
        socket.onmessage = event => {
          const data = JSON.parse(event.data)
          if (data.method === "Runtime.exceptionThrown") errors.push(data.params.exceptionDetails.text)
          if (data.id && requests.has(data.id)) {
            const { resolve, reject, timer } = requests.get(data.id)
            clearTimeout(timer); requests.delete(data.id)
            if (data.error) reject(new Error(JSON.stringify(data.error)))
            else resolve(data.result)
          }
        }
        return
      }
    } catch { await delay(150) }
  }
  throw new Error("Browser did not start")
}
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence
    const timer = setTimeout(() => { requests.delete(id); reject(new Error(`Timed out: ${method}`)) }, 15000)
    requests.set(id, { resolve, reject, timer })
    socket.send(JSON.stringify({ id, method, params }))
  })
}
async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text)
  return result.result?.value
}
async function waitFor(expression) {
  for (let attempt = 0; attempt < 80; attempt++) {
    if (await evaluate(expression)) return
    await delay(100)
  }
  throw new Error(`Condition not met: ${expression}`)
}
async function click(text) {
  await evaluate(`(() => { const button = [...document.querySelectorAll('.model-app button, .activity-nav button')].find(item => item.textContent.trim() === ${JSON.stringify(text)}); if (!button) throw Error('Missing button: ' + ${JSON.stringify(text)}); button.click(); })()`)
  await delay(100)
}
async function fill(selector, value) {
  await evaluate(`(() => { const input = document.querySelector(${JSON.stringify(selector)}); if (!input) throw Error('Missing input'); const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, ${JSON.stringify(value)}); input.dispatchEvent(new Event('input', { bubbles: true })); })()`)
}
async function screenshot(name) {
  const image = await send("Page.captureScreenshot", { format: "png" })
  await writeFile(join(outputDir, name), Buffer.from(image.data, "base64"))
}

try {
  await connect()
  await send("Runtime.enable")
  await send("Page.enable")
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false })
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `
    localStorage.setItem('vh-app-view', 'modeling');
    window.modelCalls = [];
    const originalFetch = window.fetch;
    window.modelMode = 'complete';
    let runningId = null;
    let streamController;
    const output = '\\n\u0060\u0060\u0060modeling-report\\n' + JSON.stringify({ experiments: [{ id: 0, title: '真实接口测试基线', score: 0.72, algorithm: 'LightGBM', plan: '固定验证集', result: '测试响应', code: 'print(0.72)' }] }) + '\\n\u0060\u0060\u0060';
    window.fetch = async (url, options = {}) => {
      if (typeof url !== 'string' || !url.startsWith('/api/')) return originalFetch(url, options);
      window.modelCalls.push({ url, method: options.method || 'GET', body: options.body });
      const json = data => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
      if (url === '/api/sessions' && options.method === 'POST') return json({ id: 'model-test-' + crypto.randomUUID() });
      if (url === '/api/sessions') return json({ sessions: [], running_id: runningId, model: 'test' });
      if (url.endsWith('/mode')) return json({ mode: 'plan' });
      if (url.endsWith('/messages')) {
        if (window.modelMode === 'error') return new Response(JSON.stringify({ error: 'test_failure' }), { status: 500 });
        runningId = url.split('/')[3];
        const encoder = new TextEncoder();
        const event = payload => encoder.encode('data: ' + JSON.stringify(payload) + '\\n\\n');
        return new Response(new ReadableStream({ start(controller) {
          streamController = controller;
          window.modelEmit = payload => controller.enqueue(event(payload));
          controller.enqueue(event({ kind: 'thinking_delta', text: '正在检查训练数据' }));
          controller.enqueue(event({ kind: 'tool_call_end', name: 'update_todos', arguments: { todos: [
            { content: '检查数据路径、字段、依赖和可用资源', status: 'completed' },
            { content: '创建固定训练、验证和测试集，完成数据清洗与预处理', status: 'in_progress' },
            { content: '运行基线模型并记录结果', status: 'pending' }
          ] } }));
          controller.enqueue(event({ kind: 'tool_call_end', name: 'shell', tool_call_id: 'train-1', arguments: { command: 'python train.py' } }));
          controller.enqueue(event({ kind: 'tool_execution_start', name: 'shell', tool_call_id: 'train-1' }));
          controller.enqueue(event({ kind: 'tool_result', name: '', tool_call_id: 'train-1', text: '已加载 1000 行训练数据' }));
          controller.enqueue(event({ kind: 'text_delta', origin: 'child', parent_tool_call_id: 'delegate-1', text: '子任务正在评估候选方案' }));
          if (window.modelMode !== 'running') {
            controller.enqueue(event({ kind: 'text_delta', text: output }));
            controller.enqueue(event({ kind: 'run_result', status: 'complete' }));
            controller.close(); runningId = null;
          }
        } }), { headers: { 'Content-Type': 'text/event-stream' } });
      }
      if (url.endsWith('/stop')) {
        if (window.modelMode === 'stop-error') return new Response('{}', { status: 500 });
        streamController?.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ kind: 'run_result', status: 'stopped' }) + '\\n\\n'));
        streamController?.close(); runningId = null; return json({ ok: true });
      }
      if (url.startsWith('/api/sessions/')) return json({ messages: [{ role: 'assistant', content: output }] });
      if (url === '/api/skills') return json({ skills: [] });
      if (url === '/api/workdir') return json({ path: 'workspace' });
      if (url.startsWith('/api/dirs')) return json({ path: 'workspace', dirs: [], files: [], parent: null });
      return json({});
    };
  ` })
  await send("Page.navigate", { url: "http://127.0.0.1:5181" })
  await waitFor("!!document.querySelector('.model-intro')")
  await screenshot("01-create.png")
  await click("信贷风险预测二分类 · 稳定性与可解释性")
  assert.match(await evaluate("document.querySelector('.model-config-card textarea').value"), /信贷/)
  await click("搜索策略与高级配置展开 +")
  assert.equal(await evaluate("!!document.querySelector('.model-algorithms')"), true)
  await click("示例实验演示")
  await waitFor("document.querySelectorAll('.model-step').length === 12")
  await screenshot("02-experiments.png")
  await click("最优")
  assert.equal(await evaluate("document.querySelectorAll('.model-step').length"), 1)
  await click("结果分析")
  assert.equal(await evaluate("document.querySelectorAll('.model-comparison tbody tr').length"), 12)
  await screenshot("03-analysis.png")
  await evaluate("document.querySelector('.model-chart [role=button]').dispatchEvent(new MouseEvent('click', { bubbles: true }))")
  await waitFor("!!document.querySelector('.model-experiment-detail')")
  await click("基于此方案继续探索 ↗")
  assert.equal(await evaluate("!!document.querySelector('.model-parent-note')"), true)
  await click("新建建模任务")
  await fill('.model-config-card input[maxlength="100"]', '测试建模任务')
  await fill('.model-config-card textarea', '测试二分类模型')
  await fill('input[placeholder="data/train.csv"]', 'data/train.csv')
  await fill('input[placeholder="如 default_flag"]', 'label')
  await click("开始探索")
  await waitFor("document.querySelector('.model-state')?.textContent === '执行结束'")
  assert.equal(await evaluate("document.querySelectorAll('.model-step').length"), 1)
  assert.match(await evaluate("window.modelCalls.find(call => call.url.endsWith('/messages')).body"), /测试集/)
  await click("智能体")
  await click("自进化建模")
  assert.equal(await evaluate("document.querySelector('.model-task-title h1').textContent"), '测试建模任务')
  const savedLogTimes = await evaluate("JSON.parse(localStorage.getItem('vh-modeling-sessions-v1'))[0].logs.map(entry => new Date(entry.createdAt).toISOString()).reverse()")
  await send("Page.reload")
  await waitFor("document.querySelectorAll('.model-history-item').length === 1")
  await evaluate("document.querySelector('.model-history-item').click()")
  await waitFor("document.querySelectorAll('.model-step').length === 1")
  await click("执行日志")
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.model-log-meta time')].map(item => item.dateTime)"), savedLogTimes)
  assert.match(await evaluate("document.querySelector('.model-log-panel').textContent"), /python train.py/)
  assert.match(await evaluate("document.querySelector('.model-log-panel').textContent"), /已加载 1000 行训练数据/)
  await click("任务配置")
  await click("复制为新任务 ↗")
  await evaluate("window.modelMode = 'running'")
  await click("开始探索")
  await waitFor("document.querySelector('.model-state')?.textContent === '探索中'")
  await click("执行日志")
  await waitFor("document.querySelector('.model-log-panel')?.textContent.includes('python train.py')")
  const runningLogs = await evaluate("document.querySelector('.model-log-panel').textContent")
  assert.match(runningLogs, /正在检查训练数据/)
  assert.match(runningLogs, /执行中 · shell/)
  assert.match(runningLogs, /已加载 1000 行训练数据/)
  assert.match(runningLogs, /子任务正在评估候选方案/)
  assert.match(await evaluate("document.querySelector('.model-log-entry').textContent"), /子任务正在评估候选方案/)
  assert.equal(await evaluate("document.querySelectorAll('.model-log-entry[open]').length"), 0)
  assert.match(await evaluate("document.querySelector('.model-log-meta time').textContent"), /\d{4}\/\d{2}\/\d{2}.*\d{2}:\d{2}:\d{2}/)
  await screenshot("06-running-logs.png")
  await evaluate("[...document.querySelectorAll('.model-log-summary')].find(item => item.textContent.includes('调用工具 · shell')).click()")
  assert.equal(await evaluate("[...document.querySelectorAll('.model-log-entry[open] pre')].some(item => item.textContent.includes('python train.py'))"), true)
  await evaluate("[...document.querySelectorAll('.model-log-summary')].find(item => item.textContent.includes('调用工具 · shell')).click()")
  await evaluate("[...document.querySelectorAll('.model-log-summary')].find(item => item.textContent.includes('update_todos')).click()")
  assert.equal(await evaluate("document.querySelectorAll('.model-log-entry[open] .model-log-todos li').length"), 3)
  assert.equal(await evaluate("document.querySelector('.model-log-raw').open"), false)
  await evaluate("window.modelEmit({kind: 'thinking_delta', text: '准备下一轮训练'})")
  await waitFor("document.querySelector('.model-log-entry')?.textContent.includes('准备下一轮训练')")
  assert.equal(await evaluate("document.querySelector('.model-log-todos').closest('details').open"), true)
  await screenshot("07-expanded-log.png")
  await send("Emulation.setDeviceMetricsOverride", { width: 430, height: 932, deviceScaleFactor: 1, mobile: false })
  assert.equal(await evaluate("document.documentElement.scrollWidth <= 430"), true)
  await screenshot("08-mobile-logs.png")
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false })
  await click("深度研究")
  await click("自进化建模")
  await evaluate("window.modelMode = 'stop-error'")
  await click("停止探索")
  await waitFor("document.querySelector('.model-alert.error')?.textContent.includes('停止失败')")
  assert.equal(await evaluate("document.querySelector('.model-state').textContent"), "探索中")
  await evaluate("window.modelMode = 'running'")
  await click("停止探索")
  await waitFor("document.querySelector('.model-state')?.textContent === '已停止'")
  await click("任务配置")
  await click("复制为新任务 ↗")
  await evaluate("window.modelMode = 'error'")
  await click("开始探索")
  await waitFor("document.querySelector('.model-state')?.textContent === '执行失败'")
  await send("Emulation.setDeviceMetricsOverride", { width: 430, height: 932, deviceScaleFactor: 1, mobile: false })
  await click("新建建模任务")
  await screenshot("04-mobile.png")
  assert.equal(await evaluate("document.documentElement.scrollWidth <= 430"), true)
  await click("示例实验演示")
  await click("结果分析")
  assert.equal(await evaluate("document.documentElement.scrollWidth <= 430"), true)
  await screenshot("05-mobile-analysis.png")
  assert.deepEqual(errors, [])
  console.log("PASS: templates, configuration, demo, filtering, chart, continuation, real API contract, streaming, navigation, history, stop failures, stop, request errors, mobile overflow, runtime errors")
  console.log(`Screenshots: ${outputDir}`)
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    try { await send("Browser.close") } catch { browser.kill() }
    socket.close()
  } else browser.kill()
}

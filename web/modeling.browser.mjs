import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { mkdir, mkdtemp, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { defaultModelConfig } from "./src/features/autoresearch/config.ts"

const profile = await mkdtemp(join(tmpdir(), "vector-modeling-browser-"))
const outputDir = join(tmpdir(), "vector-modeling-preview")
await mkdir(outputDir, { recursive: true })
const chrome = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe"
const debugPort = Number(process.env.BROWSER_DEBUG_PORT || 9347)
const browser = spawn(chrome, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, "about:blank"], { windowsHide: true, stdio: "ignore" })
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))
let socket
let sequence = 0
const requests = new Map()
const errors = []
async function connect() {
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json()
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
  await evaluate(`(() => { const button = [...document.querySelectorAll('.model-app button, .research-app button, .activity-nav button, .activity-logo, .home-page button')].find(item => item.getClientRects().length && (item.getAttribute('aria-label') === ${JSON.stringify(text)} || item.textContent.trim() === ${JSON.stringify(text)})); if (!button) throw Error('Missing button: ' + ${JSON.stringify(text)}); button.click(); })()`)
  await delay(100)
}
async function fill(selector, value) {
  await evaluate(`(() => { const input = document.querySelector(${JSON.stringify(selector)}); if (!input) throw Error('Missing input'); const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, ${JSON.stringify(value)}); input.dispatchEvent(new Event('input', { bubbles: true })); })()`)
}
async function screenshot(name) {
  const image = await send("Page.captureScreenshot", { format: "png" })
  await writeFile(join(outputDir, name), Buffer.from(image.data, "base64"))
}

async function resizeSidebar(selector, delta) {
  const point = await evaluate(`(() => { const rect = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return {x: rect.x + rect.width / 2, y: rect.y + rect.height * 0.3} })()`)
  await send("Input.dispatchMouseEvent", {type: "mouseMoved", ...point})
  await send("Input.dispatchMouseEvent", {type: "mousePressed", button: "left", buttons: 1, clickCount: 1, ...point})
  await send("Input.dispatchMouseEvent", {type: "mouseMoved", button: "left", buttons: 1, x: point.x + delta, y: point.y})
  await send("Input.dispatchMouseEvent", {type: "mouseReleased", button: "left", buttons: 0, clickCount: 1, x: point.x + delta, y: point.y})
  await delay(100)
}

try {
  await connect()
  await send("Runtime.enable")
  await send("Page.enable")
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false })
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.modelCalls = [];
    window.homeSessions = [];
    const originalFetch = window.fetch;
    window.modelMode = 'complete';
    let runningId = null;
    let streamController;
    const defaults = ${JSON.stringify(defaultModelConfig)};
    const modelOptions = {defaults, fields: {
      name: {type: 'string'}, description: {type: 'string', required: true}, dataPath: {type: 'string', required: true}, target: {type: 'string', required: true},
      metric: {type: 'string', enumByTask: {'二分类': ['AUC-ROC', 'F1'], '多分类': ['F1'], '回归': ['MAE', 'RMSE'], '服务端任务': ['ServerScore']}},
      threshold: {type: 'number', minimum: -1, maximumByMetric: {'AUC-ROC': 1, F1: 1, ServerScore: 17}, defaultByTask: {'二分类': 0.85, '多分类': 0.6, '回归': 2.5, '服务端任务': 12}},
      timeColumn: {type: 'string', requiredWhen: {split: 'time'}}, testRatio: {type: 'number', minimum: 8, maximum: 35}, maxSteps: {type: 'integer', minimum: 2, maximum: 77}, hours: {type: 'number', minimum: 0.25, maximum: 9.5}, parallel: {type: 'integer', minimum: 1, maximum: 4}
    }, enums: {task: ['二分类', '多分类', '回归', '服务端任务'], metric: ['AUC-ROC', 'F1', 'MAE', 'RMSE', 'ServerScore'], split: ['random', 'time', 'server-split'], strategy: ['多路择优', '顺序迭代', '服务器策略'], algorithms: ['LightGBM', 'XGBoost', 'ServerAlgorithm']}};
    const tasks = JSON.parse(sessionStorage.getItem('mock-server-tasks') || '{}');
    const save = () => sessionStorage.setItem('mock-server-tasks', JSON.stringify(tasks));
    window.serverTasks = tasks;
    window.saveMockTasks = save;
    window.dropModelStream = () => streamController?.close();
    window.finishDetachedTask = () => {tasks[runningId].status = 'interrupted'; tasks[runningId].revision += 1; save(); runningId = null;};
    const experiment = {id: 0, title: '真实接口测试基线', score: 0.72, algorithm: 'LightGBM', plan: '固定验证集', result: '测试响应', code: 'print(0.72)', duration: '1s', improvement: 0, improved: false, isBest: true};
    const messages = [{role: 'assistant', content: '', created_at: 1795163415, tool_calls: [{id: 'train-1', name: 'shell', arguments: {command: 'python train.py'}}]}, {role: 'tool', content: '已加载 1000 行训练数据', tool_call_id: 'train-1', created_at: 1795163416}];
    const output = '\\n\u0060\u0060\u0060modeling-report\\n' + JSON.stringify({ experiments: [{ id: 0, title: '真实接口测试基线', score: 0.72, algorithm: 'LightGBM', plan: '固定验证集', result: '测试响应', code: 'print(0.72)' }] }) + '\\n\u0060\u0060\u0060';
    window.fetch = async (url, options = {}) => {
      if (typeof url !== 'string' || !url.startsWith('/api/')) return originalFetch(url, options);
      window.modelCalls.push({ url, method: options.method || 'GET', body: options.body });
      const json = data => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
      if (url.startsWith('/api/sessions')) return json({ sessions: window.homeSessions, running_id: runningId, model: 'test' });
      if (url === '/api/autoresearch/options') return json(modelOptions);
      if (url === '/api/autoresearch/tasks' || url === '/api/deepresearch/tasks') {
        const kind = url.split('/')[2];
        if (options.method === 'POST') {
          const input = JSON.parse(options.body);
          const task = {id: 'model-test-' + crypto.randomUUID(), kind, config: input.config || input, topic: input.topic, status: 'idle', updated_at: 1795163415, revision: 0};
          tasks[task.id] = task; save(); return json(task);
        }
        const response = json({tasks: Object.values(tasks).filter(task => task.kind === kind), running_id: runningId});
        if (kind === 'deepresearch' && window.holdResearchList) {
          window.holdResearchList = false;
          return new Promise(resolve => {window.releaseResearchList = () => {delete window.releaseResearchList; resolve(response);};});
        }
        return response;
      }
      if (url.endsWith('/run') || url.endsWith('/messages')) {
        runningId = url.split('/')[4];
        const task = tasks[runningId];
        if (window.modelMode === 'error') {task.status = 'error'; save(); runningId = null; return new Response(JSON.stringify({ error: 'test_failure' }), { status: 500 });}
        task.status = 'running'; task.revision += 1; save();
        const encoder = new TextEncoder();
        const event = payload => encoder.encode('data: ' + JSON.stringify(payload) + '\\n\\n');
        return new Response(new ReadableStream({ start(controller) {
          streamController = controller;
          window.modelEmit = payload => controller.enqueue(event(payload));
          controller.enqueue(event({kind: 'task_snapshot', task, revision: task.revision}));
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
            Object.assign(task, {status: 'completed', experiments: [experiment], baselineId: 0, bestId: 0, metricDirection: 'maximize', improvement: 0, output, revision: task.revision + 1}); save();
            controller.enqueue(event({kind: 'task_snapshot', task, revision: task.revision}));
            controller.enqueue(event({ kind: 'text_delta', text: output }));
            controller.enqueue(event({ kind: 'run_result', status: 'complete' }));
            controller.close(); runningId = null;
          }
        } }), { headers: { 'Content-Type': 'text/event-stream' } });
      }
      if (url.endsWith('/stop')) {
        if (window.modelMode === 'stop-error') return new Response('{}', { status: 500 });
        if (runningId) {tasks[runningId].status = 'stopped'; tasks[runningId].revision += 1; save();}
        streamController?.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ kind: 'run_result', status: 'stopped' }) + '\\n\\n'));
        streamController?.close(); runningId = null; return json({ ok: true });
      }
      if (url.includes('/tasks/')) {
        const id = url.split('/')[4];
        if (options.method === 'DELETE') {delete tasks[id]; save(); return json({deleted: true});}
        const response = tasks[id] ? json({task: tasks[id], messages, warnings: []}) : new Response(JSON.stringify({error: 'not_found'}), {status: 404});
        if (window.holdTaskDetail === id) {
          window.holdTaskDetail = null;
          return new Promise(resolve => {window.releaseTaskDetail = (status = 200) => {delete window.releaseTaskDetail; resolve(status === 200 ? response : new Response(JSON.stringify({error: 'delayed_failure'}), {status}));};});
        }
        return response;
      }
      if (url === '/api/skills') return json({ skills: [] });
      if (url === '/api/workdir') return json({ path: 'workspace' });
      if (url.startsWith('/api/dirs')) return json({ path: 'workspace', dirs: [], files: [], parent: null });
      return json({});
    };
  ` })
  await send("Page.navigate", { url: "http://127.0.0.1:5181" })
  await waitFor("!!document.querySelector('.home-page')")
  assert.equal(await evaluate("document.querySelectorAll('.home-workspace-card').length"), 3)
  await waitFor("document.querySelector('.home-empty')?.textContent.includes('从第一个任务开始')")
  await screenshot("09-home.png")
  const brandPositions = []
  for (const [label, selector] of [["进入智能体", ".brand-name"], ["进入深度研究", ".research-title-name"], ["进入自进化建模", ".model-brand-name"]]) {
    await click(label)
    brandPositions.push(await evaluate(`(() => { const title = document.querySelector('${selector} strong').getBoundingClientRect(); const subtitle = document.querySelector('${selector} small').getBoundingClientRect(); return [title.x, title.y, subtitle.x, subtitle.y] })()`))
    await click("返回首页")
  }
  assert.deepEqual(brandPositions[0], brandPositions[1])
  assert.deepEqual(brandPositions[0], brandPositions[2])
  for (const [label, panel, divider] of [["进入智能体", ".sidebar", ".app > .session-sidebar-divider"], ["进入深度研究", ".research-left", ".research-app .session-sidebar-divider"], ["进入自进化建模", ".model-sidebar", ".model-app .session-sidebar-divider"]]) {
    const handle = `${divider} .panel-resize-left`
    await click(label)
    assert.equal(await evaluate(`!!document.querySelector('${handle}')`), true)
    const before = await evaluate(`document.querySelector('${panel}').getBoundingClientRect().width`)
    await resizeSidebar(handle, 80)
    const after = await evaluate(`document.querySelector('${panel}').getBoundingClientRect().width`)
    assert.ok(Math.abs(after - before - 80) < 1, `${label} sidebar should follow the drag: ${before} -> ${after}`)
    await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: 900, y: 400})
    assert.equal(await evaluate(`document.querySelector('${panel}').getBoundingClientRect().width`), after)
    await evaluate(`document.querySelector('${divider} button').click()`)
    await waitFor(`document.querySelector('${panel}').getBoundingClientRect().width === 0`)
    assert.equal(await evaluate(`document.querySelector('${divider} button').getAttribute('aria-expanded')`), "false")
    await click("返回首页")
    await click(label)
    assert.equal(await evaluate(`document.querySelector('${panel}').getBoundingClientRect().width`), 0)
    await evaluate(`document.querySelector('${divider} button').click()`)
    await waitFor(`document.querySelector('${panel}').getBoundingClientRect().width > 0`)
    assert.equal(await evaluate(`document.querySelector('${panel}').getBoundingClientRect().width`), after)
    await evaluate(`document.querySelector('${handle}').focus()`)
    await send("Input.dispatchKeyEvent", {type: "keyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39})
    await send("Input.dispatchKeyEvent", {type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39})
    await waitFor(`Math.abs(document.querySelector('${panel}').getBoundingClientRect().width - ${after + 10}) < 1`)
    await resizeSidebar(handle, -10)
    await resizeSidebar(handle, -80)
    if (label === "进入自进化建模") {
      await screenshot("12-sidebar-expanded.png")
      await evaluate(`document.querySelector('${divider} button').click()`)
      await screenshot("13-sidebar-collapsed.png")
      await evaluate(`document.querySelector('${divider} button').click()`)
    }
    await click("返回首页")
  }
  assert.equal(await evaluate("window.modelCalls.filter(call => call.method === 'POST').length"), 0)
  const navPoint = await evaluate("(() => { const rect = document.querySelector('.activity-item[aria-label=深度研究]').getBoundingClientRect(); return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2} })()")
  await send("Input.dispatchMouseEvent", {type: "mouseMoved", ...navPoint})
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#activity-description-deepresearch')).visibility"), "hidden")
  await waitFor("getComputedStyle(document.querySelector('#activity-description-deepresearch')).opacity === '1'")
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#activity-description-deepresearch')).backgroundColor"), "rgb(37, 53, 77)")
  assert.match(await evaluate("document.querySelector('#activity-description-deepresearch').textContent"), /参考来源/)
  await screenshot("10-navigation-tooltip.png")
  const tooltipPoint = await evaluate("(() => { const rect = document.querySelector('#activity-description-deepresearch').getBoundingClientRect(); return {x: rect.x + 20, y: rect.y + 20} })()")
  await send("Input.dispatchMouseEvent", {type: "mouseMoved", ...tooltipPoint})
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#activity-description-deepresearch')).visibility"), "visible")
  await send("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27})
  await send("Input.dispatchKeyEvent", {type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27})
  await waitFor("getComputedStyle(document.querySelector('#activity-description-deepresearch')).visibility === 'hidden'")
  await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: 800, y: 100})
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#activity-description-deepresearch')).visibility"), "hidden")
  await send("Page.reload")
  await waitFor("!!document.querySelector('.home-page')")
  await click("进入智能体")
  await evaluate("document.querySelector('.activity-logo').focus()")
  assert.equal(await evaluate("document.activeElement.classList.contains('activity-logo')"), true)
  await send("Input.dispatchKeyEvent", {type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r"})
  await send("Input.dispatchKeyEvent", {type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13})
  await waitFor("!!document.querySelector('.home-page')")
  await evaluate("window.homeSessions = [{id: 'recent-home-test', title: '最近的研究会话', updated_at: Date.now() / 1000, mode: 'act', skills: null}]")
  await waitFor("document.querySelector('.home-recent-item')?.textContent.includes('最近的研究会话')")
  await evaluate("document.querySelector('.home-recent-item').click()")
  await waitFor("document.querySelector('.session-item.is-open')?.textContent.includes('最近的研究会话')")
  assert.ok(await evaluate("window.modelCalls.some(call => call.url === '/api/sessions/recent-home-test')"))
  await click("返回首页")
  await send("Emulation.setDeviceMetricsOverride", { width: 430, height: 932, deviceScaleFactor: 1, mobile: false })
  assert.equal(await evaluate("document.documentElement.scrollWidth <= 430"), true)
  await screenshot("11-mobile-home.png")
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false })
  await evaluate("window.homeSessions = []")
  await click("进入自进化建模")
  await waitFor("!!document.querySelector('.model-intro')")
  await screenshot("01-create.png")
  await click("信贷风险预测二分类 · 稳定性与可解释性")
  assert.match(await evaluate("document.querySelector('.model-config-card textarea').value"), /信贷/)
  await click("搜索策略与高级配置展开 +")
  assert.equal(await evaluate("!!document.querySelector('.model-algorithms')"), true)
  assert.match(await evaluate("document.querySelector('.model-algorithms').textContent"), /ServerAlgorithm/)
  assert.equal(await evaluate("document.querySelector('input[name=maxSteps]').max"), "77")
  assert.equal(await evaluate("document.querySelector('input[name=hours]').max"), "9.5")
  assert.equal(await evaluate("document.querySelector('input[name=testRatio]').min"), "8")
  assert.match(await evaluate("document.querySelector('select[name=strategy]').textContent"), /服务器策略/)
  assert.match(await evaluate("document.querySelector('select[name=split]').textContent"), /server-split/)
  await evaluate("document.querySelector('select[name=task]').value = '服务端任务'; document.querySelector('select[name=task]').dispatchEvent(new Event('change', {bubbles: true}))")
  await waitFor("document.querySelector('select[name=metric]').value === 'ServerScore'")
  assert.equal(await evaluate("document.querySelector('input[name=threshold]').value"), "12")
  assert.equal(await evaluate("document.querySelector('input[name=threshold]').max"), "17")
  await evaluate("document.querySelector('select[name=task]').value = '回归'; document.querySelector('select[name=task]').dispatchEvent(new Event('change', {bubbles: true}))")
  await waitFor("document.querySelector('select[name=metric]').value === 'MAE'")
  assert.equal(await evaluate("document.querySelector('input[name=threshold]').value"), "2.5")
  assert.equal(await evaluate("document.querySelector('input[name=threshold]').max"), "")
  await click("示例实验演示")
  await waitFor("document.querySelectorAll('.model-step').length === 12")
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.model-step.is-selected')).boxShadow"), "none")
  await screenshot("02-experiments.png")
  await click("最优")
  assert.equal(await evaluate("document.querySelectorAll('.model-step').length"), 1)
  await click("结果分析")
  assert.equal(await evaluate("document.querySelectorAll('.model-comparison tbody tr').length"), 12)
  await screenshot("03-analysis.png")
  await evaluate("document.querySelector('.model-chart [role=button]').dispatchEvent(new MouseEvent('click', { bubbles: true }))")
  await waitFor("!!document.querySelector('.model-experiment-detail')")
  await click("基于此方案继续探索 ↗")
  assert.equal(await evaluate("!!document.querySelector('.model-parent-note')"), false)
  await click("新建建模任务")
  await fill('.model-config-card input[name="name"]', '测试建模任务')
  await fill('.model-config-card textarea', '测试二分类模型')
  await fill('input[placeholder="data/train.csv"]', 'data/train.csv')
  await fill('input[placeholder="如 default_flag"]', 'label')
  await click("开始探索")
  await waitFor("document.querySelector('.model-state')?.textContent === '执行结束'")
  assert.equal(await evaluate("document.querySelectorAll('.model-step').length"), 1)
  assert.equal(await evaluate("JSON.parse(window.modelCalls.find(call => call.url === '/api/autoresearch/tasks' && call.method === 'POST').body).config.description"), "测试二分类模型")
  assert.equal(await evaluate("window.modelCalls.find(call => call.url.endsWith('/run')).body"), "{}")
  assert.equal(await evaluate("window.modelCalls.some(call => call.url.endsWith('/mode') || call.url.endsWith('/messages'))"), false)
  await click("智能体")
  await click("自进化建模")
  assert.equal(await evaluate("document.querySelector('.model-task-title h1').textContent"), '测试建模任务')
  assert.equal(await evaluate("localStorage.getItem('vh-modeling-sessions-v1')"), null)
  await click("执行日志")
  const savedLogTimes = await evaluate("[...document.querySelectorAll('.model-log-meta time')].map(item => item.dateTime)")
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
  await click("返回首页")
  await waitFor("!!document.querySelector('.home-page')")
  await evaluate("window.modelEmit({kind: 'text_delta', origin: 'child', parent_tool_call_id: 'delegate-1', text: '，首页期间继续运行'})")
  await click("进入自进化建模")
  assert.equal(await evaluate("document.querySelector('.model-state').textContent"), "探索中")
  await waitFor("document.querySelector('.model-log-panel')?.textContent.includes('首页期间继续运行')")
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
  await click("任务配置")
  await click("复制为新任务 ↗")
  await evaluate("window.modelMode = 'running'")
  await click("开始探索")
  await waitFor("document.querySelector('.model-state')?.textContent === '探索中'")
  const detailReads = await evaluate("window.modelCalls.filter(call => call.url.includes('/tasks/') && call.method === 'GET').length")
  await evaluate("window.dropModelStream()")
  await waitFor(`window.modelCalls.filter(call => call.url.includes('/tasks/') && call.method === 'GET').length > ${detailReads}`)
  assert.equal(await evaluate("document.querySelector('.model-state').textContent"), "探索中")
  await evaluate("window.finishDetachedTask()")
  await waitFor("document.querySelector('.model-state')?.textContent === '执行中断'")
  await evaluate(`window.serverTasks.research = {id: 'research', kind: 'deepresearch', config: {topic: '服务端研究', engine: 'standard'}, topic: '服务端研究', status: 'completed', updated_at: 1795163415, revision: 5, tasks: [{id: 'stable-b', index: 0, title: '第二方向', description: '', status: 'unknown'}, {id: 'stable-a', index: 1, title: '第一方向', description: '', status: 'completed'}], details: {'stable-b': {queries: ['server query'], notePath: 'notes/b.md', inferred: true, sources: [{title: '服务端来源', url: 'https://example.com/b', inferred: true}], summary: '稳定 ID 对应的服务端摘要'}, 'stable-a': {queries: [], notePath: null, sources: [], summary: '另一摘要'}}, progress: {done: 1, total: 2}, report: '服务端研究报告'}; window.saveMockTasks()`)
  await click("深度研究")
  await waitFor("document.querySelectorAll('.research-task-card').length === 2")
  assert.equal(await evaluate("document.querySelector('.research-task-card').classList.contains('unknown')"), true)
  assert.equal(await evaluate("document.querySelector('.research-task-badge').textContent.trim()"), "状态未知")
  assert.match(await evaluate("document.querySelector('.research-progress-label').textContent"), /1 \/ 2/)
  await evaluate("document.querySelector('.research-task-card').click()")
  await waitFor("document.querySelector('.research-detail')?.textContent.includes('稳定 ID 对应的服务端摘要') || document.querySelector('.research-main')?.textContent.includes('稳定 ID 对应的服务端摘要')")
  assert.match(await evaluate("document.querySelector('.research-detail-inference').textContent"), /推断.*未经核实/)
  assert.match(await evaluate("document.querySelector('.research-source-inference').textContent"), /推断来源.*未经核实/)
  await evaluate("window.serverTasks.research.tasks.reverse(); window.serverTasks.research.revision += 1; window.saveMockTasks()")
  await waitFor("document.querySelector('.research-task-card')?.textContent.includes('第一方向')")
  assert.match(await evaluate("document.querySelector('.research-task-card.is-selected').textContent"), /第二方向/)
  assert.match(await evaluate("document.querySelector('.research-main').textContent"), /稳定 ID 对应的服务端摘要/)
  await evaluate("document.querySelector('.research-engine-select').value = 'standard'; document.querySelector('.research-engine-select').dispatchEvent(new Event('change', {bubbles: true})); window.modelMode = 'complete'")
  await fill('.research-topic-input', '接口主题')
  await click("+ 开始新研究")
  await waitFor("window.modelCalls.some(call => call.url === '/api/deepresearch/tasks' && call.method === 'POST')")
  assert.deepEqual(await evaluate("JSON.parse(window.modelCalls.find(call => call.url === '/api/deepresearch/tasks' && call.method === 'POST').body)"), {topic: "接口主题", engine: "standard"})
  await waitFor("document.querySelector('.research-status-label')?.textContent === '研究完成'")
  await fill('.research-followup-input', '只发送用户后续问题')
  await click("发送")
  await waitFor("window.modelCalls.some(call => call.url.endsWith('/messages'))")
  assert.deepEqual(await evaluate("JSON.parse(window.modelCalls.find(call => call.url.endsWith('/messages')).body)"), {text: "只发送用户后续问题"})
  await waitFor("document.querySelector('.research-status-label')?.textContent === '研究完成'")
  await evaluate("window.holdTaskDetail = 'research'; window.holdResearchList = true; [...document.querySelectorAll('.research-history-item')].find(item => item.textContent.includes('服务端研究')).click()")
  await waitFor("!!window.releaseTaskDetail && !!window.releaseResearchList")
  await click("删除任务")
  await waitFor("![...document.querySelectorAll('.research-history-item')].some(item => item.textContent.includes('服务端研究'))")
  await evaluate("window.releaseResearchList(); window.releaseTaskDetail()")
  await delay(250)
  assert.equal(await evaluate("[...document.querySelectorAll('.research-history-item')].some(item => item.textContent.includes('服务端研究'))"), false)
  assert.match(await evaluate("document.querySelector('.research-heading-title').textContent"), /接口主题/)
  assert.equal(await evaluate("document.querySelector('.research-error')?.textContent ?? ''"), "")
  await evaluate("window.serverTasks.other = {...Object.values(window.serverTasks).find(task => task.kind === 'deepresearch'), id: 'other', topic: '另一任务'}; window.saveMockTasks()")
  await waitFor("[...document.querySelectorAll('.research-history-item')].some(item => item.textContent.includes('另一任务'))")
  await evaluate("[...document.querySelectorAll('.research-history-item')].find(item => item.textContent.includes('另一任务')).click(); window.holdTaskDetail = Object.values(window.serverTasks).find(task => task.topic === '接口主题').id")
  await delay(100)
  await evaluate("[...document.querySelectorAll('.research-history-item')].find(item => item.textContent.includes('接口主题')).click()")
  await waitFor("!!window.releaseTaskDetail")
  await evaluate("[...document.querySelectorAll('.research-history-item')].find(item => item.textContent.includes('另一任务')).click()")
  await delay(100)
  await evaluate("window.releaseTaskDetail(500)")
  await delay(100)
  assert.equal(await evaluate("document.querySelector('.research-error')?.textContent ?? ''"), "")
  await evaluate("delete window.serverTasks.other; window.saveMockTasks()")
  await waitFor("![...document.querySelectorAll('.research-history-item')].some(item => item.textContent.includes('另一任务'))")
  await waitFor("document.querySelector('.research-heading-title')?.textContent.includes('接口主题')")
  const removedReads = await evaluate("window.modelCalls.filter(call => call.url === '/api/deepresearch/tasks/other' && call.method === 'GET').length")
  const refreshes = await evaluate("window.modelCalls.filter(call => call.url === '/api/deepresearch/tasks').length")
  await waitFor(`window.modelCalls.filter(call => call.url === '/api/deepresearch/tasks').length > ${refreshes}`)
  assert.equal(await evaluate("window.modelCalls.filter(call => call.url === '/api/deepresearch/tasks/other' && call.method === 'GET').length"), removedReads)
  assert.equal(await evaluate("document.querySelector('.research-error')?.textContent ?? ''"), "")
  await click("自进化建模")
  await send("Emulation.setDeviceMetricsOverride", { width: 430, height: 932, deviceScaleFactor: 1, mobile: false })
  await click("新建建模任务")
  await screenshot("04-mobile.png")
  assert.equal(await evaluate("document.documentElement.scrollWidth <= 430"), true)
  await click("示例实验演示")
  await click("结果分析")
  assert.equal(await evaluate("document.documentElement.scrollWidth <= 430"), true)
  await screenshot("05-mobile-analysis.png")
  assert.deepEqual(errors, [])
  console.log("PASS: templates, configuration, demo, filtering, chart, continuation, task API contracts, streaming, navigation, history, stop failures, stop, request errors, disconnect recovery, research stable IDs, unknown status, inferred evidence, follow-up text, deletion and navigation races, mobile overflow, runtime errors")
  console.log(`Screenshots: ${outputDir}`)
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    try { await send("Browser.close") } catch { browser.kill() }
    socket.close()
  } else browser.kill()
}

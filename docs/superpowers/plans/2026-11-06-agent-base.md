# Agent 基座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个可导入的 Python agent 基座：核心是工具循环、模型接口、默认工具和 JSONL 会话，五个模式模块由调用方在外面装配。

**Architecture:** `vector_harness.core` 与 `vector_harness.tools` 不导入 `patterns` 或 `cli`。模式要么是 `Loop` 的 `context_transforms`（只有压缩），要么是工具或包住 `Loop` 的外层（计划）。终端 `build_agent` 是唯一的产品装配点。测试用 `tests/scripted.py` 里的假 Provider，不访问网络。

**Tech Stack:** Python 3.11+、标准库 `dataclass`、官方 `openai` 客户端、pytest。包布局 `src/vector_harness`。测试用 `httpx.MockTransport` 伪造 HTTP。

**Spec:** `docs/superpowers/specs/2026-11-06-agent-base-design.md`

## Global Constraints

- Python 3.11+。运行环境包括 Windows。路径用 `pathlib`，比较前 `resolve()`，再用 `relative_to`。
- 分发包和导入名都是 `vector_harness`。控制台脚本名 `vector-harness`。
- 生产依赖只有官方 `openai` 客户端。不用 LangChain、PyYAML、pytest-asyncio。客户端自带的库不在业务代码里直接使用。
- 数据对象用 `dataclass`。API 全是异步。不提供同步包装。
- 测试函数保持同步，内部用 `asyncio.run`。假模型放在 `tests/scripted.py`，不放进安装包。
- `core/`、`tools/`、包根 `__init__.py` 的源码不得导入 `vector_harness.patterns` 或 `vector_harness.cli`。
- 错误文本按本计划的固定字符串断言，不要另写措辞。
- 模型密钥只来自 `VECTOR_API_KEY`，不能做命令行参数。

固定错误与标记：

- 工作目录外的路径：`Error: path is outside the workspace`
- `old_string` 不是恰好一次：`Error: old_string must appear exactly once`
- 文件已存在且 `old_string` 为空：`Error: old_string must be non-empty when the file exists`
- 未知工具：`Error: Unknown tool: {name}`
- 工具参数不是 dict：`Error: invalid arguments for {name}`
- 未知 skill：`Error: Unknown skill: {name}`
- 命令超时：`Error: command timed out after {timeout}s`
- 命令输出截断后缀：`\n...[truncated]`
- 读文件截断后缀：`\n...[truncated, more lines remain]`
- 压缩摘要消息正文以 `[compacted context]\n` 开头
- 计划失败文本以 `Invalid plan JSON:` 开头
- 子循环未完成时，工具结果为 `[{status}] {text}`

## Review Focus

下面五种输入最容易在真实使用时咬人。每条都已经写进对应任务的测试。

1. 模型调用了未注册的工具，或参数不是对象：循环要把 `Error: ...` 写进工具消息并再问一次模型，`run` 不能把异常抛出进程。任务 3。
2. 工作目录内的符号链接解析后落到目录外：读和改都拒绝，目录外的文件字节不变。任务 5。
3. 会话字符数已超过上限，但尾部之前没有可摘要的消息：压缩不得调用模型，会话字节不变。任务 7。
4. HTTP 401 只请求 1 次；429 最多 3 次尝试（含第一次）。第 3 次仍是 429 时抛 `ProviderError`。任务 4。
5. 命令超过调用方传入的超时：数秒内返回超时错误，而不是等到默认的 120 秒。任务 6。

## File Map

| 文件 | 职责 |
|------|------|
| `pyproject.toml` | 包元数据、脚本入口、pytest 的 `pythonpath = src` |
| `src/vector_harness/types.py` | `ToolCall`、`Message`、`RunResult`、`ProviderEvent`、`Tool`、`ContextTransform` |
| `src/vector_harness/__init__.py` | 只导出核心与默认工具，不导入模式 |
| `src/vector_harness/core/session.py` | JSONL 会话的追加与整文件重写 |
| `src/vector_harness/core/loop.py` | 工具循环、事件、步数、工具失败 |
| `src/vector_harness/core/provider.py` | OpenAI 兼容流式 HTTP、重试、`from_env` |
| `src/vector_harness/tools/read.py` | `ReadFile` |
| `src/vector_harness/tools/edit.py` | `EditFile` |
| `src/vector_harness/tools/shell.py` | `Shell` |
| `src/vector_harness/patterns/compact.py` | `Compaction` |
| `src/vector_harness/patterns/skills.py` | `Skills` |
| `src/vector_harness/patterns/plan.py` | `PlanThenExecute` |
| `src/vector_harness/patterns/subagent.py` | `delegate_tool` |
| `src/vector_harness/patterns/memory.py` | `Memory` |
| `src/vector_harness/cli.py` | 参数、装配、单次任务、逐行交互 |
| `tests/scripted.py` | `ScriptedProvider` |
| `tests/test_*.py` | 各任务的测试 |

最终 `vector_harness.__init__` 导出：`Message`、`ToolCall`、`RunResult`、`ProviderEvent`、`Loop`、`Session`、`OpenAICompatibleProvider`、`ReadFile`、`EditFile`、`Shell`。模式类不在这个列表里。各任务只把自己新增的名字加进去。

---

### Task 1: 包骨架与类型

**Files:**
- Create: `pyproject.toml`
- Create: `src/vector_harness/__init__.py`
- Create: `src/vector_harness/types.py`
- Create: `src/vector_harness/core/__init__.py`
- Create: `src/vector_harness/tools/__init__.py`
- Create: `src/vector_harness/patterns/__init__.py`
- Test: `tests/test_import_boundary.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `ToolCall(id: str, name: str, arguments: dict)`
  - `Message(role: str, content: str, tool_calls: list[ToolCall] | None = None, tool_call_id: str | None = None, is_error: bool = False)`
  - `RunResult(status: str, text: str, steps: int, session_path: Path | None)`
  - `ProviderEvent(kind: str, text: str = "", name: str = "", tool_call_id: str = "", arguments: dict | None = None)`
  - `Tool` 协议：属性 `name: str`、`description: str`、`parameters: dict`，方法 `async execute(self, arguments: dict) -> str`
  - `ContextTransform` 协议：`async apply(self, messages: list[Message]) -> list[Message]`

- [ ] **Step 1: Write the failing test**

```python
def test_package_root_does_not_import_patterns_or_cli():
    import sys
    import vector_harness
    assert "vector_harness.patterns" not in sys.modules
    assert "vector_harness.cli" not in sys.modules
    offenders = imports_of(src_roots)
    assert offenders == []
```

`imports_of` 用 `ast` 扫描 `src/vector_harness/__init__.py`、`core/`、`tools/` 里每个 `.py`。`Import` 与 `ImportFrom` 的模块名包含 `vector_harness.patterns` 或 `vector_harness.cli` 时记入 offenders。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_import_boundary.py -v`  
Expected: FAIL，`vector_harness` 无法导入。

- [ ] **Step 3: Implement the package skeleton**

`pyproject.toml`：`name = "vector_harness"`，`requires-python = ">=3.11"`，`dependencies = ["openai"]`，可选依赖 `dev = ["pytest", "httpx"]`，脚本 `vector-harness = "vector_harness.cli:main"`，setuptools 从 `src` 找包。pytest `pythonpath = ["src"]`。

`types.py` 按 Interfaces 写 `dataclass` 与 `Protocol`。`__init__.py` 只导出 `Message`、`ToolCall`、`RunResult`、`ProviderEvent`。三个子包的 `__init__.py` 为空。然后执行 `python -m pip install -e ".[dev]"`。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/vector_harness tests/test_import_boundary.py
git commit -m "feat: add package skeleton and core types"
```

### Task 2: JSONL 会话

**Files:**
- Create: `src/vector_harness/core/session.py`
- Modify: `src/vector_harness/__init__.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `Message`、`ToolCall`
- Produces:
  - `Session(path: Path | None)`
  - `Session.in_memory() -> Session`
  - `Session.path: Path | None`
  - `Session.load() -> list[Message]`
  - `Session.append(message: Message) -> None`
  - `Session.replace_all(messages: list[Message]) -> None`

每行一个 JSON 对象，键固定为 `role`、`content`、`tool_calls`、`tool_call_id`、`is_error`。`tool_calls` 为 `null` 或对象列表，元素键为 `id`、`name`、`arguments`。文件不存在或为空时 `load()` 返回 `[]`。`append` 创建缺失的父目录。`replace_all` 重写整个文件，不在末尾追加。`in_memory()` 的 `path` 为 `None`，不创建文件。

- [ ] **Step 1: Write the failing test**

覆盖三件事：缺失文件 `load()` 为 `[]`；`append` 一条带 `tool_calls` 的助手消息和一条 `is_error=True` 的工具消息后，读回字段相等，文件有 2 行；先写入 3 条再 `replace_all` 为 1 条，文件只剩 1 行。另外 `Session.in_memory().path is None`，`append` 后 `load()` 能读回，且临时目录里没有新文件。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session.py -v`  
Expected: FAIL，`Session` 不存在。

- [ ] **Step 3: Implement `Session` in `src/vector_harness/core/session.py`**

按上面的文件格式读写。包根 `__init__.py` 增加导出 `Session`。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_session.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/core/session.py src/vector_harness/__init__.py tests/test_session.py
git commit -m "feat: persist sessions as JSONL"
```

### Task 3: 工具循环

**Files:**
- Create: `src/vector_harness/core/loop.py`
- Create: `tests/scripted.py`
- Modify: `src/vector_harness/__init__.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `Message`、`ToolCall`、`RunResult`、`ProviderEvent`、`Session`、`Tool`、`ContextTransform`
- Produces:
  - `Loop(*, provider, tools: list, session: Session, system: str, context_transforms: list | None = None, on_event: Callable[[ProviderEvent], None] | None = None, max_steps: int = 25)`
  - `Loop.run(user_text: str) -> RunResult`（async）
  - `Loop.max_steps: int`、`Loop.system: str`、`Loop.context_transforms: list`、`Loop.tools: list`
  - `ScriptedProvider(turns: list[ScriptedTurn])`，`ScriptedTurn(content: str = "", tool_calls: list[ToolCall] | None = None)`
  - `ScriptedProvider.calls: list[dict]`，每项有 `system`、`messages`、`tools`（工具名列表）
  - `ScriptedProvider.stream(*, system, messages, tools)` 异步生成 `ProviderEvent`。有文本时先产生 `text_delta`；每个工具调用先 `tool_call_start` 再 `tool_call_end`（`arguments` 为 dict）。回合用尽时抛 `AssertionError("no scripted turns left")`，不要抛 `ProviderError`。

循环规则：`run` 先把用户文本 `append` 进会话。一步是一次 `stream` 调用。每步之前按顺序 `await transform.apply(messages)`；只有序列化后的消息变化时才 `replace_all` 并保存。变换看到的列表里没有 system，system 单独作为 `stream` 的参数。助手回合有工具调用时，先写助手消息，再逐个 `execute`，再写 `tool` 消息。`execute` 抛异常时，工具消息 `is_error=True`，`content` 为异常文本，循环继续。没有该名字的工具时不调用 `execute`，写入 `Error: Unknown tool: {name}` 且 `is_error=True`。`arguments` 不是 `dict` 时同样不调用 `execute`，写入 `Error: invalid arguments for {name}`。没有工具调用时写入助手消息，返回 `status="complete"`，`text` 为助手正文，`steps` 为模型请求次数。`tool_call_start` 事件必须在对应 `execute` 之前交给 `on_event`。达到 `max_steps` 时，这一步若已产生工具调用，仍然执行并写入，然后返回 `status="max_steps"`，不再发起下一次模型请求；`text` 为空字符串。`run` 结束时发出 `kind="run_end"`。

- [ ] **Step 1: Write the failing test**

`tests/test_loop.py` 断言：

- 构造 `Loop` 后 `max_steps == 25`。
- 假模型先调用名为 `read_file` 的工具，再回复最终文本。`status == "complete"`，工具被调用，会话角色顺序是 `user`、`assistant`、`tool`、`assistant`。
- `max_steps=1` 且模型每次都调用工具：`status == "max_steps"`，`steps == 1`，工具执行了一次，`stream` 只被调用一次。
- 工具 `execute` 抛 `RuntimeError("boom")`：下一次模型请求能看到内容含 `boom` 的工具消息，且该消息 `is_error is True`；随后模型给出最终回复，`status == "complete"`。
- 模型调用 `missing`：会话里有 `Error: Unknown tool: missing`，`is_error is True`，然后最终回复使 `status == "complete"`。
- 有一个很小的 provider 直接产出 `ProviderEvent(kind="tool_call_end", name="read_file", arguments=["not-a-dict"])`，不要用 `ToolCall`。工具 `execute` 不被调用，会话含 `Error: invalid arguments for read_file`。
- `on_event` 收到的 `tool_call_start` 发生在 `execute` 之前，并且最后有 `run_end`。
- 变换记录到的消息角色里没有 `system`；`stream` 收到的 `system` 等于构造时的系统文本。变换若返回内容相同的副本，会话文件字节不变。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_loop.py -v`  
Expected: FAIL，`Loop` 或 `ScriptedProvider` 不存在。

- [ ] **Step 3: Implement `Loop` and `ScriptedProvider`**

`loop.py` 只依赖类型、会话和标准库。`__init__.py` 增加导出 `Loop`。`ScriptedProvider` 放在 `tests/scripted.py`。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_loop.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/core/loop.py src/vector_harness/__init__.py tests/scripted.py tests/test_loop.py
git commit -m "feat: run a tool loop with scripted turns"
```

### Task 4: OpenAI 兼容 Provider

**Files:**
- Create: `src/vector_harness/core/provider.py`
- Modify: `src/vector_harness/core/loop.py`
- Modify: `src/vector_harness/types.py`
- Modify: `src/vector_harness/__init__.py`
- Test: `tests/test_provider.py`

**Interfaces:**
- Consumes: `Message`、`ToolCall`、`ProviderEvent`、`Loop`、`Session`
- Produces:
  - `ProviderError(Exception)`，定义在 `types.py`。`Loop` 从 `types` 导入它，不要从 `provider` 导入。
  - `OpenAICompatibleProvider(*, api_key: str, base_url: str, model: str, max_attempts: int = 3, sleep: Callable = asyncio.sleep, transport: httpx.BaseTransport | None = None)`
  - `OpenAICompatibleProvider.from_env(env: Mapping[str, str] | None = None) -> OpenAICompatibleProvider`
  - `stream(*, system: str, messages: list[Message], tools: list) -> AsyncIterator[ProviderEvent]`

`from_env` 读取 `VECTOR_API_KEY`、`VECTOR_BASE_URL`、`VECTOR_MODEL`。缺任何一个都抛 `ProviderError`，消息里含该变量名。检查顺序是密钥、基址、模型。没有默认基址。

请求：`POST {base_url去尾部斜杠}/chat/completions`，头 `Authorization: Bearer {api_key}`，body 含 `model`、`stream: true`、`messages`。system 是第一条 `role=system` 的消息。工具按 OpenAI function 形式放进 `tools`。401 和其他非 429 的 4xx 不重试。429 与 5xx 最多 3 次尝试，含第一次。测试注入的 `sleep` 必须被调用，但测试里用立刻返回的协程，避免真实等待。3 次仍失败抛 `ProviderError`。

SSE 组装：把 `choices[0].delta.content` 拼成文本；`delta.tool_calls[]` 按 `index` 合并，`id` 与 `function.name` 取首次出现的值，`function.arguments` 按片段拼接后再 `json.loads`。解析失败时，该调用的 `arguments` 为 `{"_invalid_json": "<raw>"}`。流结束时生成已完成的 `tool_call_end` 事件。`data: [DONE]` 结束。

`Loop.run` 只捕获 `ProviderError`，返回 `RunResult(status="error", text=str(exc), steps=已尝试的模型请求次数, session_path=session.path)`。其他异常继续抛出。

- [ ] **Step 1: Write the failing test**

用 `httpx.MockTransport` 断言：

- 缺少 `VECTOR_API_KEY` 时 `from_env` 的 `ProviderError` 消息含 `VECTOR_API_KEY`。基址和模型都缺时同样先报告密钥。只缺 `VECTOR_MODEL` 时消息含 `VECTOR_MODEL`。
- 一段 SSE 先产出文本 `hi`，再把 `read_file` 的参数片段 `{"path":` 与 `"a.txt"}` 拼成一条工具调用，`arguments == {"path": "a.txt"}`。
- 401 只产生 1 次 HTTP 请求。400 也只产生 1 次。一次 500 然后 200：共 2 次请求并成功。连续 429 然后 200：共 2 次请求并成功。连续 3 次 429：共 3 次请求，抛 `ProviderError`。
- `Loop` 的 provider 直接抛 `ProviderError("down")` 时，`status == "error"`，`text == "down"`。provider 抛 `RuntimeError` 时，异常穿出 `run`。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_provider.py -v`  
Expected: FAIL，`OpenAICompatibleProvider` 不存在。

- [ ] **Step 3: Implement the provider and the `ProviderError` branch in `Loop`**

把 `ProviderError` 放进 `types.py`。`__init__.py` 增加导出 `OpenAICompatibleProvider`。重试间隔由 `sleep` 参数决定，默认 `asyncio.sleep`；具体秒数实现自定，测试不依赖它。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_provider.py tests/test_loop.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/core/provider.py src/vector_harness/core/loop.py src/vector_harness/types.py src/vector_harness/__init__.py tests/test_provider.py
git commit -m "feat: add an OpenAI-compatible streaming provider"
```

### Task 5: 读文件与改文件

**Files:**
- Create: `src/vector_harness/tools/read.py`
- Create: `src/vector_harness/tools/edit.py`
- Modify: `src/vector_harness/__init__.py`
- Test: `tests/test_files.py`

**Interfaces:**
- Consumes: 无（工具对象自带 `name`、`description`、`parameters`、`execute`）
- Produces:
  - `ReadFile(root: Path)`，`name == "read_file"`，参数 `path`（必填）、`offset`（默认 1，从 1 计）、`limit`（默认 200）
  - `EditFile(root: Path)`，`name == "edit_file"`，参数 `path`、`old_string`、`new_string`

读文件输出为 `{行号}|{原文}`，行号不补空格。默认最多 200 行，被截断时末尾加上 `\n...[truncated, more lines remain]`，不包含未读行的正文。`offset` 超出文件时返回 `Error: offset out of range`。

改文件：`old_string` 必须恰好出现一次，否则不写文件。文件不存在且 `old_string == ""` 时创建父目录并写入 `new_string`。路径拒绝与读文件相同，不读不写。

两个工具在预期拒绝时返回以 `Error: ` 开头的字符串，不抛异常。

- [ ] **Step 1: Write the failing test**

在临时目录建立 `root/inside.txt` 和 `root` 外的 `outside.txt`（正文 `OUTSIDE_SECRET`）。断言：

- 读取 `../outside.txt` 得到 `Error: path is outside the workspace`，结果不含 `OUTSIDE_SECRET`，外面的文件字节不变。
- 若平台允许创建符号链接，在 `root/link.txt` 指向 `outside.txt`，读取和改写该链接都返回同一条路径错误，`outside.txt` 字节不变。不能创建链接时跳过这一条，并写明原因。
- 201 行的文件默认读取不含第 201 行正文，含 `\n...[truncated, more lines remain]`，第一行以 `1|` 开头。
- 只有 1 行的文件、`offset=5` 时返回 `Error: offset out of range`。
- `old_string` 出现 0 次或 2 次时文件字节不变，返回 `Error: old_string must appear exactly once`。
- 已存在文件且 `old_string` 为空时文件不变，返回 `Error: old_string must be non-empty when the file exists`。
- 文件不存在且 `old_string` 为空时创建出 `new_string` 的内容。
- 恰好一次匹配时只替换那一处。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_files.py -v`  
Expected: FAIL，`ReadFile` 不存在。

- [ ] **Step 3: Implement `ReadFile` and `EditFile`**

路径判断：`root.resolve()` 与目标 `resolve()` 后 `relative_to`。失败即返回路径错误。`__init__.py` 导出这两个类。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_files.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/tools/read.py src/vector_harness/tools/edit.py src/vector_harness/__init__.py tests/test_files.py
git commit -m "feat: read and edit files inside a workspace"
```

### Task 6: 跑命令

**Files:**
- Create: `src/vector_harness/tools/shell.py`
- Modify: `src/vector_harness/__init__.py`
- Test: `tests/test_shell.py`

**Interfaces:**
- Consumes: 无
- Produces: `Shell(root: Path, timeout: int = 120, max_output: int = 8000)`，`name == "shell"`，模型参数只有 `command: str`

成功结果的文本含 `exit_code={code}`、`stdout:`、`stderr:`。stdout 与 stderr 合计格式化后的结果超过 `max_output` 时，保留前 `max_output` 个字符并加上 `\n...[truncated]`。工作目录是 `root`。超时用下面的进程树终止，测试不需要改这个算法：

```python
proc = subprocess.Popen(command, shell=True, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    out, err = proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    proc.communicate()
    return f"Error: command timed out after {timeout}s"
```

库里的 `Shell` 自己不打印命令。打印留给终端。

- [ ] **Step 1: Write the failing test**

断言：

- `Shell(root).timeout == 120`。
- `python -c "import pathlib; print(pathlib.Path.cwd())"` 的 stdout 含 `root` 的解析路径，且结果含 `exit_code=0`。
- `Shell(root, timeout=1)` 执行 `python -c "import time; time.sleep(30)"`，在 5 秒内返回 `Error: command timed out after 1s`。
- `Shell(root, max_output=100)` 执行打印 9000 个 `x` 的 Python 命令，结果含 `\n...[truncated]`，且截断标记之前的长度不超过 100。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_shell.py -v`  
Expected: FAIL，`Shell` 不存在。

- [ ] **Step 3: Implement `Shell`**

`__init__.py` 导出 `Shell`。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_shell.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/tools/shell.py src/vector_harness/__init__.py tests/test_shell.py
git commit -m "feat: run workspace shell commands with a timeout"
```

### Task 7: 上下文压缩

**Files:**
- Create: `src/vector_harness/patterns/compact.py`
- Test: `tests/test_compact.py`

**Interfaces:**
- Consumes: `ContextTransform`、`Provider` 的 `stream`、`Message`、`Session`、`Loop`
- Produces:
  - `Compaction(provider, *, max_chars: int, keep_last: int)`
  - `Compaction.max_chars: int`、`Compaction.keep_last: int`、`Compaction.last_failure: str | None`
  - `async apply(self, messages: list[Message]) -> list[Message]`

字符数等于所有消息 `content` 的长度，加上每条工具调用的 `name` 与 `json.dumps(arguments, sort_keys=True)` 的长度。`len(messages) <= keep_last` 时不调用 provider，`last_failure` 保持 `None`，原列表内容不变。超过上限时只摘要前缀，尾部 `keep_last` 条原样保留。前缀格式化成一条 user 文本，每行 `{role}: {content}`，`stream` 的 `tools` 为空。成功时用一条 `user` 消息替换前缀，正文是 `[compacted context]\n` 加上模型文本，`last_failure = None`。`stream` 抛异常时 `apply` 返回与输入等价的消息，`last_failure` 为异常文本。一次 `apply` 最多调用一次摘要。

- [ ] **Step 1: Write the failing test**

断言：

- 三条内容各 10 个字符的用户消息，`max_chars=25`，`keep_last=1`，摘要结果为 `SHORT`：返回两条消息，第一条 content 为 `[compacted context]\nSHORT`，第二条是原来的最后一条。摘要那次调用的 `tools == []`。
- 一条助手消息 content 为空，但工具参数 `{"a": "12345"}` 使字符数超过 `max_chars=5`，`keep_last=1`，且前面还有一条用户消息：会发生压缩。这锁住「工具参数计入字符数」。
- 只有尾部、没有前缀时，provider 的 `calls` 仍为空，消息不变。
- 摘要抛 `RuntimeError("summarizer down")` 时，`apply` 返回的消息与输入逐项相同，`last_failure == "summarizer down"`。把这些消息先 `replace_all` 进会话，调用失败的 `apply` 之后再 `load()`，两次 `load()` 的角色、正文和工具调用都相同，且正文里没有 `[compacted context]`。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_compact.py -v`  
Expected: FAIL，`Compaction` 不存在。

- [ ] **Step 3: Implement `Compaction`**

不要改 `Loop`。失败只记在 `last_failure` 上。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_compact.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/patterns/compact.py tests/test_compact.py
git commit -m "feat: compact long transcripts before each model call"
```

### Task 8: Skills

**Files:**
- Create: `src/vector_harness/patterns/skills.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: `Tool` 所需的四个成员
- Produces:
  - `Skills(directory: Path)`
  - `Skills.index_prompt() -> str`
  - `Skills.read_tool() -> Tool`，工具名 `read_skill`，参数 `name: str`

目录里每个含 frontmatter 的 `*.md` 文件，以及每个子目录里的 `SKILL.md`，都是一项 skill。frontmatter 是文件开头的 `---\n` 到下一个 `\n---\n`，只解析单行 `key: value`。`name` 和 `description` 必填。不用 PyYAML。索引按 `name` 排序，格式固定为：

```text
Skills:
- {name}: {description}
```

每项一行。目录不存在时 `index_prompt()` 返回 `""`。`read_skill` 按 frontmatter 的 `name` 返回正文（不含 frontmatter）。名字不存在时返回 `Error: Unknown skill: {name}`，不抛异常。

- [ ] **Step 1: Write the failing test**

建一个子目录 `SKILL.md`，`name: alpha`，`description: first skill`，正文 `ALPHA_BODY`。再在目录根放一个 `beta.md`，描述 `second skill`。断言索引同时含 `alpha`、`first skill`、`beta`、`second skill`，且 `alpha` 排在 `beta` 前面。`read_tool().execute({"name": "alpha"})` 返回的字符串含 `ALPHA_BODY`、不含 `first skill`。未知名字返回 `Error: Unknown skill: missing`。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skills.py -v`  
Expected: FAIL，`Skills` 不存在。

- [ ] **Step 3: Implement `Skills`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skills.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/patterns/skills.py tests/test_skills.py
git commit -m "feat: load skills by name from markdown files"
```

### Task 9: 先计划再执行

**Files:**
- Create: `src/vector_harness/patterns/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `Loop`、`Session`、`Provider.stream`、`RunResult`、`EditFile`
- Produces:
  - `format_plan(steps: list[str]) -> str`，形如 `Plan:\n1. alpha`
  - `PlanThenExecute(loop: Loop)`，属性 `loop`
  - `async run(self, user_text: str) -> RunResult`

计划请求使用 `loop.provider`，`tools` 为空，不经过 `Loop.run`。第一次请求的消息里要有本次的 `user_text`。系统提示要求模型只返回 `{"steps": ["..."]}` 这种 JSON。合法 JSON 是对象，且 `steps` 为字符串列表。`{"steps":[1]}` 与无法 `json.loads` 的文本都非法。第一次非法时，把以 `Invalid plan JSON:` 开头的说明作为下一次计划请求的用户消息再问一次。第二次仍非法：返回 `status="error"`，`steps == 2`，不调用 `Loop.run`，不往会话追加计划。成功时先 `session.append` 一条用户消息，内容是 `format_plan` 的结果，再 `await loop.run(user_text)`。不在执行中重新规划。

- [ ] **Step 1: Write the failing test**

- 第一次返回 `{"steps":[1]}`，第二次返回 `{"steps":["alpha"]}`。第一次 `stream` 的 `tools == []`，且消息里含有用户目标 `ship it`。执行阶段的工具在 `execute` 里断言会话已经含有 `1. alpha`。工作目录里的目标文件直到 `execute` 才被修改。这次成功运行有 1 次计划请求和 2 次执行期模型请求（工具调用，然后最终回复），`result.steps == 3`。
- 连续两次内容都是 `nope`：`status == "error"`，`text` 以 `Invalid plan JSON:` 开头，`steps == 2`，`EditFile` 没有创建文件，脚本里更后面的工具回合没有被消费（`ScriptedProvider` 若被多叫一次会抛 `AssertionError`）。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plan.py -v`  
Expected: FAIL，`PlanThenExecute` 不存在。

- [ ] **Step 3: Implement `PlanThenExecute`**

只捕获计划文本的解析失败和 `ProviderError`。不要捕获 `AssertionError` 或其他异常。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_plan.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/patterns/plan.py tests/test_plan.py
git commit -m "feat: plan once before the tool loop"
```

### Task 10: 子 agent

**Files:**
- Create: `src/vector_harness/patterns/subagent.py`
- Test: `tests/test_subagent.py`

**Interfaces:**
- Consumes: `Loop`、`Session.in_memory`、`RunResult`、`Tool`
- Produces: `delegate_tool(*, provider, tools: list, system: str, context_transforms: list | None = None, max_steps: int = 10) -> Tool`，工具名 `delegate`，参数 `task: str`

`execute` 新建 `Session.in_memory()` 和子 `Loop`。子工具列表是入参去掉所有 `name == "delegate"` 的工具。子循环使用传入的 `context_transforms` 与 `max_steps`。子会话不写入父会话文件。父工具结果在子 `status == "complete"` 时就是子 `RunResult.text`；否则是 `[{status}] {text}`。

- [ ] **Step 1: Write the failing test**

断言 `inspect.signature(delegate_tool).parameters["max_steps"].default == 10`。

共享一个 `ScriptedProvider`：父回合调用 `delegate`，任务文本为 `find the token`；子回合回复 `CHILD-ONLY`；父回合再回复 `parent-done`。传给工厂的工具含 `delegate` 自己和一个名为 `echo` 的工具。断言：

- 子那次 `stream` 的工具名列表含 `echo`、不含 `delegate`，消息里含有 `find the token`。
- 传入的 `context_transforms` 有一个会在 `apply` 时记下调用次数的对象。子循环跑完后，这个次数至少是 1。
- 父会话里对应工具消息的 content 是 `CHILD-ONLY`。
- 父会话里没有 `role == "assistant"` 且 content 为 `CHILD-ONLY` 的消息。
- `max_steps=1` 且子模型一直调用 `echo` 时，父工具结果以 `[max_steps]` 开头，子 `stream` 只被调用一次。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_subagent.py -v`  
Expected: FAIL，`delegate_tool` 不存在。

- [ ] **Step 3: Implement `delegate_tool`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_subagent.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/patterns/subagent.py tests/test_subagent.py
git commit -m "feat: delegate one task to a child loop"
```

### Task 11: 长期记忆

**Files:**
- Create: `src/vector_harness/patterns/memory.py`
- Test: `tests/test_memory.py`

**Interfaces:**
- Consumes: `Tool`
- Produces:
  - `Memory(path: Path)`
  - `Memory.prompt() -> str`，文件不存在时返回 `""`，存在时返回文件全文
  - `Memory.remember_tool() -> Tool`，工具名 `remember`，参数 `text: str`

`remember` 创建缺失的父目录和文件，追加一行 `- {date.today().isoformat()}: {text}\n`。不提供删除。

- [ ] **Step 1: Write the failing test**

文件尚不存在时 `prompt()` 为 `""`。`execute({"text": "remember me"})` 之后，文件全文匹配 `^- \d{4}-\d{2}-\d{2}: remember me\n$`，并且第二次 `prompt()` 含 `remember me`。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory.py -v`  
Expected: FAIL，`Memory` 不存在。

- [ ] **Step 3: Implement `Memory`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory.py tests/test_import_boundary.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/patterns/memory.py tests/test_memory.py
git commit -m "feat: append long-term memory to a markdown file"
```

### Task 12: 终端装配

**Files:**
- Create: `src/vector_harness/cli.py`
- Modify: `README.md`（只改「仓库状态」/ Status 两段）
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 前面所有公开类型与 `Compaction`、`Skills`、`PlanThenExecute`、`delegate_tool`、`Memory`、`ScriptedProvider`
- Produces:
  - `DEFAULT_SYSTEM = "You are a capable agent. Use tools to finish the task in the workspace."`
  - `build_agent(*, provider, workspace: Path, session: Session, skills_dir: Path | None = None, memory_path: Path | None = None, compact: bool = False, plan: bool = False, subagents: bool = False, max_steps: int = 25) -> Loop | PlanThenExecute`
  - `merged_env(env: Mapping[str, str], *, model: str | None, base_url: str | None) -> dict`
  - `main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None, provider=None, stdin_lines: list[str] | None = None) -> int`
  - 模块以 `python -m vector_harness.cli` 运行时调用 `main`

`build_agent` 的工具顺序从 `read_file`、`edit_file`、`shell` 开始。有 `skills_dir` 时追加 `read_skill`，并把 `index_prompt()` 接到系统文本后。有 `memory_path` 时再追加 `remember`，然后把 `prompt()` 接在 skills 索引之后。`compact=True` 时加入 `Compaction(provider, max_chars=80000, keep_last=8)`。`subagents=True` 时最后追加 `delegate`。`plan=True` 时返回 `PlanThenExecute`，其 `loop` 使用上面的工具、系统和变换；否则返回 `Loop`。未传任何模式时，工具只有这三个默认工具，变换为空，返回类型是 `Loop`，system 等于 `DEFAULT_SYSTEM`。

`main` 使用 argparse。不要提供 `--api-key` 或任何写入密钥的参数。`--workspace` 默认当前目录，目录必须存在，否则返回 1，stderr 含该路径。剩余参数拼成一次任务。没有任务文本时按行交互，`/exit` 结束，空行跳过，不把 `/exit` 送给模型，也不设其他斜杠命令。`--session` 使用给定路径；省略时使用 `{workspace}/.vector/sessions/{uuid4().hex}.jsonl`。不传 `--memory` 时不启用记忆。`--memory` 不带路径时使用 `{workspace}/.vector/MEMORY.md`；`--memory PATH` 使用该路径。两条路径都可以尚不存在。`--skills` 的目录必须存在，否则返回 1，stderr 含 `skills directory not found`。`--compact`、`--plan`、`--subagents`、`--max-steps` 按规格装配。`merged_env` 在传入 `model` 或 `base_url` 时覆盖 `VECTOR_MODEL`、`VECTOR_BASE_URL`，不改动密钥。`main` 把合并后的环境交给 `from_env`。未注入 `provider` 且环境缺少密钥、基址或模型时，返回 1，stderr 含 `from_env` 报出的变量名，不建立 HTTP 连接。`status == "complete"` 时返回 0，`max_steps` 和 `error` 返回 1。

`on_event`：`text_delta` 把 `event.text` 写到 stdout，不加前缀。`tool_call_end` 且 `name == "shell"` 时写 `command: {arguments["command"]}\n`。事件在 `execute` 之前发生，因为循环会先收完这一回合的流再执行工具。`--help` 的文本含 `80000` 和 `8`。

README 的中文状态改为：`目标已按上面写定。核心、五个模式和终端入口已实现。设计说明见` 原来的设计文档链接。英文 Status 改为：`The goals above are agreed. The core, five patterns, and terminal entry are implemented. See` 同一链接。其余 README 段落不动。

- [ ] **Step 1: Write the failing test**

断言：

- `from vector_harness import Loop, Session, OpenAICompatibleProvider, ReadFile, EditFile, Shell` 可以成功。`import vector_harness` 之后 `vector_harness.patterns` 仍不在 `sys.modules` 里。
- 不打开任何模式时，`build_agent(...).tools` 的名字是 `["read_file", "edit_file", "shell"]`，`context_transforms == []`，system 等于 `DEFAULT_SYSTEM`，类型是 `Loop`。
- 同时打开五个模式，且 skills 与记忆文件里有可辨认的句子：工具名顺序是 `read_file`、`edit_file`、`shell`、`read_skill`、`remember`、`delegate`；system 里 skill 名字出现在记忆句子之前；`agent.loop.context_transforms[0].max_chars == 80000` 且 `keep_last == 8`。
- 用 `subprocess` 跑 `python -m vector_harness.cli --help`，`PYTHONPATH` 含 `src`。stdout 含 `80000` 与 `8`，且不含 `api-key`。
- `merged_env({"VECTOR_API_KEY": "k", "VECTOR_MODEL": "old"}, model="new", base_url="http://example")` 得到的模型是 `new`，基址是 `http://example`，密钥仍是 `k`。
- 环境为空时 `main(["do it"])` 返回 1，stderr 含 `VECTOR_API_KEY`。密钥和基址都有、模型缺失时，stderr 含 `VECTOR_MODEL`。
- 注入 `ScriptedProvider`，参数含任务 `fix it`，且不传 `--session`：provider 收到的用户文本是 `fix it`，stdout 含模型的 `text_delta`，返回 0，并且 `workspace/.vector/sessions/` 下出现一个 `.jsonl` 文件。
- 只传 `--memory`、不传路径时，装配出的工具名单含 `remember`，记忆路径是 `workspace / ".vector" / "MEMORY.md"`。完全不传 `--memory` 时名单不含 `remember`。
- 注入的 shell 工具在 `execute` 中断言 stdout 已经含 `command: echo hi`。模型先调用 `shell`，命令是 `echo hi`。
- `stdin_lines=["hello", "/exit", "after"]` 时模型只收到 `hello`，收不到 `/exit` 和 `after`。
- `max_steps=1` 且模型一直调用工具时 `main` 返回 1。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`  
Expected: FAIL，`build_agent` 不存在。

- [ ] **Step 3: Implement `cli.py` and update the README status**

`cli.py` 可以导入模式。不要把模式导入 `core`、`tools` 或包根 `__init__.py`。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector_harness/cli.py tests/test_cli.py README.md
git commit -m "feat: add a terminal that wires patterns explicitly"
```

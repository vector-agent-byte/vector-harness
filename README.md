# Vector Harness

**Python 通用 agent 基座** — 自己调模型、自己用工具把任务做完；模式分开实现，核心可以单独嵌进真实项目。

[English](#english) · [中文](#中文)

---

## 中文

### 项目目标

**Vector Harness** 是 [vector-agent-byte](https://github.com/vector-agent-byte) 组织下的开源项目。它是一套 Python 通用 agent，参照 [nanobot](https://github.com/HKUDS/nanobot) 和 [Pi](https://github.com/earendil-works/pi)：人在终端里对一个工作目录下达目标，agent 调用模型、使用工具，并把会话留下来。

做它有两个同等重要的目标：

1. **把当前常见的 agent 设计模式各自实现一遍**，读一个模块就能看清一种模式。
2. **同一份代码能当底层基座用。** 真实项目可以只引用核心，不必带上全部模式。

### 核心

可导入的运行时，只包含四块：

- **工具循环**：模型提出工具调用，程序执行，结果喂回模型，直到答完或达到步数上限。
- **模型接口**：官方 OpenAI 客户端的 Chat Completions，调用方也可以换成自己的实现。
- **工具执行**：默认提供读文件、改文件、跑命令。路径限制在工作目录内。
- **会话记录**：JSONL 文件，可以接着上一次继续。

默认入口是终端。核心代码不导入任何模式模块。

连接信息写在 `~/.vector-harness/config.toml`：

```toml
api_key = "..."
base_url = "https://example/v1"
model = "..."
```

终端和嵌入的优先级不同：

| 调用 | 优先级 |
| --- | --- |
| 终端 | `--model`、`--base-url` 覆盖环境变量。配置文件只补还空着的 `api_key`、`base_url`、`model`。密钥没有命令行参数。 |
| `OpenAICompatibleProvider()` 不传这三项 | 配置文件里有的项优先。文件没写的项再用 `VECTOR_API_KEY`、`VECTOR_BASE_URL`、`VECTOR_MODEL`。 |
| 构造时三项都传入 | 只用传入的值。 |

### 模式

模式各自一个模块，由调用方或终端显式装配。可以单独打开，也可以同时打开。默认全部关闭。文件怎么分工、一次任务怎么走，见 [docs/architecture.md](docs/architecture.md)。

| 模式 | 作用 |
|------|------|
| **上下文压缩** | 会话变长时，把较早的消息折成一段摘要，保留最近若干条 |
| **Skills** | 索引进提示，正文按名字读取 |
| **先计划再执行** | 先要一份步骤列表，再进入工具循环 |
| **反思** | 做完之后评判一次，不通过就只再执行一版 |
| **子 agent** | 把一项任务交给一层子循环，子循环不能再派生子 agent |
| **长期记忆** | 跨会话的 Markdown 文件，用工具追加事实 |

计划和反思包在工具循环外面，不并排。只开计划时是「计划 → 工具循环」。只开反思时是「反思 → 工具循环」。两个都开时，反思在外、计划在内。反思不通过时再跑一轮内层；内层是计划的话，这一轮会重新要计划。

### 嵌入

终端之外，普通脚本用 `VectorHarness`。`llm` 只要有 `stream(system, messages, tools)`。`run` 自己开事件循环，放在普通脚本里，不要放进已经在跑的异步函数。

```python
from vector_harness import Calculator, OpenAICompatibleProvider, VectorHarness

agent = VectorHarness(
    name="助手",
    llm=OpenAICompatibleProvider(),
    system_prompt="算术必须调用 calculator。",
    tools=[Calculator()],
)
text = agent.run("2 + 3 * 4 等于多少")
```

创建时可以同时传入 `skills_dir`、`plan`、`reflect` 等，参数和终端开关对应。这些开关都关闭时，构造函数不加载模式包。已经建好的实例用 `from vector_harness import attach` 再装。`import vector_harness` 不加载模式。

不连终端的样例：`python tests/invoice_sample.py` 做账单，`python tests/skills_sample.py` 同时打开技能、计划和反思。pytest 不收集这两个文件。

### 本机网页

在仓库根目录启动：

```powershell
python -m vector_harness.web --workspace .
```

页面在 `http://127.0.0.1:8787/`。

开发页面时另开一个终端，在 `web/` 执行 `npm install` 和 `npm run dev`。Python 的端口不是 `8787` 时，设置 `VECTOR_WEB_PORT`。

要让 Python 直接提供页面，先在 `web/` 执行 `npm run build`，再启动上面同一个 Python 命令。

模式开关与终端相同，写在启动 Python 的参数里，不在页面上。

### 这一版不做

聊天渠道、定时任务、MCP、质量门、Auto Research、命令沙箱和人机确认。

### 安装

需要 Python 3.11 及以上。开发环境是 conda 的 `env-py3117`（Python 3.11.7）。在仓库根目录执行：

```powershell
conda activate env-py3117
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=1000000 -e ".[dev]"
```

这会以可编辑方式安装 `vector_harness`，并装上测试用的 `pytest` 和 `httpx`。安装指向 `src/vector_harness/`。之后改 `.py` 不用重装，重新运行即可。改了 `pyproject.toml`、增删包目录，或换了 Python 环境，再执行一次上面的命令。模型调用使用官方 `openai` 包。

### 验证

不连模型时，在仓库根目录跑测试：

```powershell
python -m pytest -q
```

全部通过即可。Windows 上若没有创建符号链接的权限，会跳过一条测试。

连模型时，把连接信息写到 `~/.vector-harness/config.toml`（Windows 上是 `%USERPROFILE%\.vector-harness\config.toml`），字段见上文。然后在仓库根目录执行：

```powershell
python -m vector_harness.cli --workspace . 读 README.md，用一句话说明这个项目做什么
```

终端会打出模型的回复。不写任务则逐行对话，输入 `/exit` 结束。需要模式时加上 `--compact`、`--skills 目录`、`--plan`、`--reflect`、`--subagents`、`--memory`。

### 仓库状态

目标已按上面写定。核心、六个模式和终端入口已实现。设计说明见 [docs/superpowers/specs/2026-11-06-agent-base-design.md](docs/superpowers/specs/2026-11-06-agent-base-design.md)。

### 相关链接

- 仓库：<https://github.com/vector-agent-byte/vector-harness>

---

## English

### Goals

**Vector Harness** is an open-source Python agent you can embed. It calls a model, uses tools, and keeps a session — in the spirit of [nanobot](https://github.com/HKUDS/nanobot) and [Pi](https://github.com/earendil-works/pi). From the terminal, you give it a goal and a working directory.

Two goals carry equal weight:

1. **Implement current agent design patterns as separate modules**, so each pattern can be read on its own.
2. **Serve as a base for real projects.** Callers can depend on the core alone and leave every pattern out.

### Core

The importable runtime is four pieces:

- **Tool loop** — the model requests tool calls, the program runs them, and results go back to the model until it answers or hits the step limit.
- **Model interface** — the official OpenAI client calling Chat Completions, plus a replaceable provider protocol.
- **Tool execution** — read files, edit files, and run commands. Paths stay inside the workspace.
- **Session** — a JSONL transcript that can be resumed.

The default entry point is the terminal. Core code does not import pattern modules.

Put the connection in `~/.vector-harness/config.toml`:

```toml
api_key = "..."
base_url = "https://example/v1"
model = "..."
```

The terminal and the embeddable provider resolve settings differently:

| Call | Precedence |
| --- | --- |
| Terminal | `--model` and `--base-url` override environment variables. The file fills only `api_key`, `base_url`, and `model` that are still empty. There is no command-line flag for the key. |
| `OpenAICompatibleProvider()` with any of the three omitted | Values in the file win. Missing file entries fall back to `VECTOR_API_KEY`, `VECTOR_BASE_URL`, and `VECTOR_MODEL`. |
| All three passed to the constructor | Only the passed values are used. |

### Patterns

Each pattern is its own module, wired explicitly by the caller or the CLI. All are off unless turned on. How the files divide and how one task runs is in [docs/architecture.md](docs/architecture.md).

| Pattern | Role |
|---------|------|
| **Context compaction** | Fold older messages into a summary and keep a recent tail |
| **Skills** | Put the index in the prompt; load a skill body by name |
| **Plan then execute** | Ask for a step list, then run the tool loop |
| **Reflection** | Judge the finished result once, and run one revision when it fails |
| **Sub-agents** | Delegate one task to a child loop that cannot delegate again |
| **Long-term memory** | A Markdown file across sessions, appended by a tool |

Plan and reflection wrap the tool loop. Plan alone is plan, then the loop. Reflection alone is reflection, then the loop. With both on, reflection is outside and plan is inside. A failed reflection runs the inner layer once more; when that layer is plan, the revision asks for a new plan.

### Embedding

Outside the terminal, a script uses `VectorHarness`. `llm` only needs `stream(system, messages, tools)`. `run` starts its own event loop, so call it from a normal script, not from a function that is already async.

```python
from vector_harness import Calculator, OpenAICompatibleProvider, VectorHarness

agent = VectorHarness(
    name="助手",
    llm=OpenAICompatibleProvider(),
    system_prompt="算术必须调用 calculator。",
    tools=[Calculator()],
)
text = agent.run("2 + 3 * 4 等于多少")
```

The constructor takes the same pattern switches as the CLI, including `skills_dir`, `plan`, and `reflect`. When every switch is off, constructing the agent does not load the pattern package. An existing instance can be extended with `from vector_harness import attach`. `import vector_harness` does not load patterns.

Samples that skip the terminal: `python tests/invoice_sample.py` for an invoice, and `python tests/skills_sample.py` with skills, plan, and reflection together. pytest does not collect either file.

### Local web

From the repository root:

```powershell
python -m vector_harness.web --workspace .
```

The page is at `http://127.0.0.1:8787/`.

To develop the page, open another terminal and, in `web/`, run `npm install` and `npm run dev`. If the Python port is not `8787`, set `VECTOR_WEB_PORT`.

To have Python serve the page, run `npm run build` in `web/`, then start the same Python command.

Pattern flags are the same as the terminal. They go on the Python command, not on the page.

### Out of this version

Chat channels, scheduled tasks, MCP, quality gates, auto research, command sandboxing, and human approval prompts.

### Install

Python 3.11 or newer. Development uses the conda env `env-py3117` (Python 3.11.7). From the repository root:

```powershell
conda activate env-py3117
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=1000000 -e ".[dev]"
```

This installs `vector_harness` in editable mode, plus `pytest` and `httpx` for tests. The install points at `src/vector_harness/`. Later edits to `.py` files are picked up the next time you run a command. Run the install again after changing `pyproject.toml`, adding or removing a package directory, or switching Python environments. Model calls use the official `openai` package.

### Verify

Without a model, from the repository root:

```powershell
python -m pytest -q
```

The suite should pass. On Windows, one test is skipped when the account cannot create symlinks.

To call a model, write `~/.vector-harness/config.toml` (on Windows, `%USERPROFILE%\.vector-harness\config.toml`) using the fields above, then from the repository root:

```powershell
python -m vector_harness.cli --workspace . 读 README.md，用一句话说明这个项目做什么
```

The terminal prints the model's reply. Omit the task to chat one line at a time, and type `/exit` to stop. Turn patterns on with `--compact`, `--skills <dir>`, `--plan`, `--reflect`, `--subagents`, or `--memory`.

### Status

The goals above are agreed. The core, six patterns, and terminal entry are implemented. See [docs/superpowers/specs/2026-11-06-agent-base-design.md](docs/superpowers/specs/2026-11-06-agent-base-design.md).

### Links

- Repository: <https://github.com/vector-agent-byte/vector-harness>

---

## License

License to be added. See repository defaults or open an issue if you need clarification before contributing.

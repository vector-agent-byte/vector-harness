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
- **工具执行**：默认提供读文件、改文件、跑命令。读和改的路径限制在工作目录内。命令在工作目录里启动，这一版不限制命令再访问哪里。
- **会话记录**：JSONL 文件。终端用 `--session` 接着写；不写时每次启动新建一份。

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

技能文件放在 `--skills` 给出的目录里：当前层的 `*.md`，以及下一层的 `SKILL.md`。文件以 `---` 开头，前言里要有 `name` 和 `description`，否则跳过。索引只含名字和说明，正文由模型调用 `read_skill` 读取。`--memory` 写到 `{workspace}/.vector/MEMORY.md`；`--memory-path` 改用指定文件，这时不必再写 `--memory`。`--compact` 在超过 80000 字符时折叠较早的消息，保留最近 8 条。

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

页面在 `web/`，用 React 和 Vite。安装后可以用 `vector-harness-web`，也可以在仓库根目录执行：

```powershell
python -m vector_harness.web --workspace .
```

只监听 `127.0.0.1`，没有 `--host`。默认地址是 `http://127.0.0.1:8787/`。`--port` 改端口，`--open` 启动后打开浏览器。连接信息的优先级和终端相同。

页面可以新建、打开和删除会话。会话留在启动时那个工作目录的 `.vector/sessions/` 里，一份会话一个 JSONL。同一时间只能跑一轮。运行中可以停止，正在执行的命令会一起结束。助手回复按 Markdown 显示。回车发送，Shift+回车换行。

每一句在页面上选择一种模式，默认是 ReAct：

| 页面 | 行为 |
| --- | --- |
| ReAct | 直接进入工具循环 |
| PlanAndSolve | 先要一份步骤列表，再进入工具循环 |
| Reflection | 做完之后评判一次，不通过就再执行一版 |

页面发出的每一句都带上当时选中的模式。`--plan` 和 `--reflect` 只留给请求里没有写模式的调用。页面上一次只用上面三种里的一种。

`--compact`、`--subagents`、`--memory`、`--memory-path`、`--max-steps` 写在启动命令上，页面上没有对应开关。`--max-steps` 默认 25。

技能目录：写了 `--skills` 就用那个目录，目录必须已经存在。没写时，如果当前目录下有 `skills/`，就用它。当前会话可以选一个技能，索引和读取都只包含这一个；选「不使用」则这一份会话不挂技能。

右侧列出工具使用的工作目录，启动时等于 `--workspace`，可以在页面上换成别的目录。会话仍留在启动时的工作目录里。有一轮正在跑时不能换。点开头的名字不列出。

开发页面时另开一个终端，在 `web/` 执行 `npm install` 和 `npm run dev`，然后打开 Vite 给出的地址。Vite 把 `/api` 转到 Python。Python 的端口不是 `8787` 时，设置 `VECTOR_WEB_PORT`。

要让 Python 直接提供页面，先在 `web/` 执行 `npm run build`，再启动上面的 Python 命令。还没构建时，打开根路径会提示先构建。

### 这一版不做

聊天渠道、定时任务、MCP、质量门、Auto Research、命令沙箱和人机确认。

### 安装

需要 Python 3.11 及以上。开发环境是 conda 的 `env-py3117`（Python 3.11.7）。在仓库根目录执行：

```powershell
conda activate env-py3117
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=1000000 -e ".[dev]"
```

这会以可编辑方式安装 `vector_harness`，并装上测试用的 `pytest` 和 `httpx`。同时注册 `vector-harness` 和 `vector-harness-web`。安装指向 `src/vector_harness/`。之后改 `.py` 不用重装，重新运行即可。改了 `pyproject.toml`、增删包目录，或换了 Python 环境，再执行一次上面的命令。模型调用使用官方 `openai` 包。网页前端的依赖在 `web/` 里另装，需要本机的 Node.js。

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

安装后也可以写成 `vector-harness`。终端打出模型的回复。思考和工具调用各占一行，并带时刻。`NO_COLOR` 或 `VECTOR_COLOR=never` 时不上色。

不写任务则逐行对话，空行跳过，输入 `/exit` 结束。某一轮没有完成就不再读后面的行。没写 `--session` 时，每次启动新建 `{workspace}/.vector/sessions/{uuid}.jsonl`。`--session` 指向一份 JSONL，就接着那份写。

常用开关：`--compact`、`--skills 目录`、`--plan`、`--reflect`、`--subagents`、`--memory`、`--memory-path 文件`、`--max-steps N`。`--max-steps` 默认 25，是这一轮里模型最多回答几次。默认工具是读文件、改文件和跑命令。

### 仓库状态

目标已按上面写定。核心、六个模式、终端和本机网页已实现。设计说明见 [docs/superpowers/specs/2026-11-06-agent-base-design.md](docs/superpowers/specs/2026-11-06-agent-base-design.md)。

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
- **Tool execution** — read files, edit files, and run commands. Read and edit stay inside the workspace. Commands start in the workspace; this version does not confine what a command can reach afterward.
- **Session** — a JSONL transcript. `--session` continues a file; omitting it starts a new one.

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

Skill files live in the `--skills` directory: `*.md` in that directory, and `SKILL.md` one level down. A file must start with `---` and include `name` and `description` in the front matter; otherwise it is skipped. The index carries names and descriptions. The model loads a body with `read_skill`. `--memory` appends to `{workspace}/.vector/MEMORY.md`. `--memory-path` selects another file and does not require `--memory`. `--compact` folds older messages after 80000 characters and keeps the last 8.

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

The page lives in `web/` and is built with React and Vite. After install, use `vector-harness-web`, or from the repository root:

```powershell
python -m vector_harness.web --workspace .
```

It binds only to `127.0.0.1`. There is no `--host`. The default address is `http://127.0.0.1:8787/`. `--port` changes the port, and `--open` opens a browser after startup. Connection settings follow the same precedence as the terminal.

The page can create, open, and delete sessions. They stay under `.vector/sessions/` in the workspace given at startup, one JSONL file each. Only one turn runs at a time. Stopping a turn also stops a command that is still running. Assistant replies render as Markdown. Enter sends; Shift+Enter inserts a newline.

Each message uses one mode chosen on the page. The default is ReAct:

| On the page | Behavior |
| --- | --- |
| ReAct | Go straight into the tool loop |
| PlanAndSolve | Ask for a step list, then run the tool loop |
| Reflection | Judge the finished result once, and run one revision when it fails |

Every message from the page includes the selected mode. `--plan` and `--reflect` apply only when a request omits the mode. The page uses one of the three modes above for a message.

`--compact`, `--subagents`, `--memory`, `--memory-path`, and `--max-steps` stay on the startup command. The page has no switches for them. `--max-steps` defaults to 25.

Skills: `--skills` selects a directory, and that directory must already exist. When the flag is omitted, `skills/` under the current directory is used if it exists. A session can select one skill; the index and `read_skill` then include only that skill. Choosing none leaves skills off for that session.

The right-hand panel lists the directory tools use. It starts as `--workspace` and can be changed on the page. Sessions remain in the startup workspace. The directory cannot be changed while a turn is running. Names that start with a dot are hidden.

To develop the page, open another terminal and, in `web/`, run `npm install` and `npm run dev`, then open the address Vite prints. Vite proxies `/api` to Python. If the Python port is not `8787`, set `VECTOR_WEB_PORT`.

To have Python serve the page, run `npm run build` in `web/`, then start the Python command above. Before that build, the root URL tells you to build first.

### Out of this version

Chat channels, scheduled tasks, MCP, quality gates, auto research, command sandboxing, and human approval prompts.

### Install

Python 3.11 or newer. Development uses the conda env `env-py3117` (Python 3.11.7). From the repository root:

```powershell
conda activate env-py3117
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=1000000 -e ".[dev]"
```

This installs `vector_harness` in editable mode, plus `pytest` and `httpx` for tests. It also registers `vector-harness` and `vector-harness-web`. The install points at `src/vector_harness/`. Later edits to `.py` files are picked up the next time you run a command. Run the install again after changing `pyproject.toml`, adding or removing a package directory, or switching Python environments. Model calls use the official `openai` package. Frontend dependencies live in `web/` and need Node.js on the machine.

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

After install, `vector-harness` is the same command. The terminal prints the model's reply. Thinking and tool calls each take a line, with a timestamp. `NO_COLOR` or `VECTOR_COLOR=never` turns color off.

Omit the task to chat one line at a time. Blank lines are skipped, and `/exit` stops without sending that line. A turn that does not finish stops the input loop. Without `--session`, each start creates `{workspace}/.vector/sessions/{uuid}.jsonl`. `--session` points at a JSONL file and continues it.

Common flags: `--compact`, `--skills <dir>`, `--plan`, `--reflect`, `--subagents`, `--memory`, `--memory-path <file>`, and `--max-steps N`. `--max-steps` defaults to 25 and is how many model replies one turn may take. The default tools are read, edit, and shell.

### Status

The goals above are agreed. The core, six patterns, terminal, and local web page are implemented. See [docs/superpowers/specs/2026-11-06-agent-base-design.md](docs/superpowers/specs/2026-11-06-agent-base-design.md).

### Links

- Repository: <https://github.com/vector-agent-byte/vector-harness>

---

## License

License to be added. See repository defaults or open an issue if you need clarification before contributing.

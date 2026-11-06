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
- **模型接口**：OpenAI Chat Completions 兼容的 HTTP 实现，调用方也可以换成自己的实现。
- **工具执行**：默认提供读文件、改文件、跑命令。路径限制在工作目录内。
- **会话记录**：JSONL 文件，可以接着上一次继续。

默认入口是终端。核心代码不导入任何模式模块。

### 模式

模式各自一个模块，由调用方或终端显式装配。可以单独打开，也可以同时打开。默认全部关闭。

| 模式 | 作用 |
|------|------|
| **上下文压缩** | 会话变长时，把较早的消息折成一段摘要，保留最近若干条 |
| **Skills** | 索引进提示，正文按名字读取 |
| **先计划再执行** | 先要一份步骤列表，再进入工具循环 |
| **子 agent** | 把一项任务交给一层子循环，子循环不能再派生子 agent |
| **长期记忆** | 跨会话的 Markdown 文件，用工具追加事实 |

### 这一版不做

聊天渠道、Web UI、定时任务、MCP、质量门、Auto Research、命令沙箱和人机确认。

### 仓库状态

目标已按上面写定。实现尚未开始。设计说明见 [docs/superpowers/specs/2026-11-06-agent-base-design.md](docs/superpowers/specs/2026-11-06-agent-base-design.md)。

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
- **Model interface** — one OpenAI Chat Completions-compatible HTTP implementation, plus a replaceable provider protocol.
- **Tool execution** — read files, edit files, and run commands. Paths stay inside the workspace.
- **Session** — a JSONL transcript that can be resumed.

The default entry point is the terminal. Core code does not import pattern modules.

### Patterns

Each pattern is its own module, wired explicitly by the caller or the CLI. All are off unless turned on.

| Pattern | Role |
|---------|------|
| **Context compaction** | Fold older messages into a summary and keep a recent tail |
| **Skills** | Put the index in the prompt; load a skill body by name |
| **Plan then execute** | Ask for a step list, then run the tool loop |
| **Sub-agents** | Delegate one task to a child loop that cannot delegate again |
| **Long-term memory** | A Markdown file across sessions, appended by a tool |

### Out of this version

Chat channels, a web UI, scheduled tasks, MCP, quality gates, auto research, command sandboxing, and human approval prompts.

### Status

The goals above are agreed. Implementation has not started. See [docs/superpowers/specs/2026-11-06-agent-base-design.md](docs/superpowers/specs/2026-11-06-agent-base-design.md).

### Links

- Repository: <https://github.com/vector-agent-byte/vector-harness>

---

## License

License to be added. See repository defaults or open an issue if you need clarification before contributing.

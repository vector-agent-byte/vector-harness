# Agent 基座设计

日期：2026-11-06  
状态：已确认

## 意图

做一套 Python 通用 agent，自己调模型、自己用工具把任务做完。参照物是 nanobot 和 Pi（earendil 的 pi-agent）：一条工具循环，会话留得下来，人能在终端里对一个工作目录下目标。

做它有两个同等重要的原因。第一，把现在常见的 agent 设计模式各自实现一遍，读代码就能学。第二，以后真实项目能把同一份代码当底层基座引用，不必带上全部模式。

仓库 README 的项目目标已按本设计改写。质量门和 Auto Research 不实现。

## 目标

- 一个可导入的核心：工具循环、模型接口、工具执行、会话记录。
- 默认工具：读文件、改文件、跑命令。默认入口：终端。
- 六个模式模块，可以单独或同时接上：上下文压缩、skills、先计划再执行、反思、子 agent、长期记忆。
- 核心代码不导入任何模式模块。模式由调用方或终端入口在外面装配。
- 用假模型做测试，不依赖真实 API key。每种模式有测试能单独说明它的行为。
- 库的调用方可以只依赖核心和默认工具完成一次带工具的运行。

## 非目标

这一版不做：

- 聊天渠道、Web UI、定时任务、常驻消息网关
- MCP、多模型厂商的原生 SDK、向量库记忆、自动研究、质量门
- 子 agent 递归、并行子 agent、执行中途重新规划
- 人机确认弹窗、命令白名单、安全沙箱
- 除 `~/.vector-harness/config.toml` 以外的配置文件。该文件只放连接信息：`api_key`、`base_url`、`model`

## 反目标

就算能跑，下面几种结果也算失败：

- 模式只是核心循环里的开关，必须顺着一个大文件才能看完一种模式
- 真实项目引用核心时必须导入模式模块
- 只能演示、不能 `import` 进别的 Python 项目
- 默认行为把计划模式或子 agent 打开，调用方不写装配也会走进这些模式

## 约束

- 语言：Python 3.11+
- 仓库：`vector-harness`。分发包和导入名都叫 `vector_harness`
- 依赖只允许标准库和官方 `openai` 客户端。不用 LangChain 或其他 agent 框架。客户端自己带的 HTTP 库和模型解析库随它安装，业务代码不直接使用它们
- 运行环境包括 Windows。路径用 `pathlib`。命令在工作目录下通过系统 shell 执行
- 核心必须能在没有网络的测试里跑完，模型用假实现

## 做法

考虑过三种做法。

1. **核心和模式分开。** 核心只有循环、模型、工具、会话，不引用模式。模式各自一个模块，由入口装配。真项目可以只引用核心；学习时一个文件看完一种模式。代价是同时打开几种模式时，装配写在入口。
2. **一个 Agent 类，模式做成开关。** 调用短，但每种模式在循环里留钩子，核心变成交汇处。
3. **每种模式一个能单独跑的小 agent。** 对照着看最清楚，但模型调用和工具执行会复制多份，基座不成立。

nanobot 那种消息总线加常驻网关不采用。渠道和定时任务不在这一版里。

作者选择第一种，因为两个目的都要：核心可嵌入，模式仍然各自完整。

## 已定的结构

```
src/vector_harness/
  __init__.py          # 只导出核心类型，不导入 patterns
  types.py             # Message、Tool、RunResult 等
  core/
    loop.py            # 工具循环
    provider.py        # 模型接口与 OpenAI 兼容实现
    session.py         # JSONL 会话
  tools/
    read.py
    edit.py
    shell.py
  patterns/
    compact.py
    skills.py
    plan.py
    reflect.py
    subagent.py
    memory.py
  cli.py               # 唯一允许同时导入 core、tools、patterns 的产品入口
tests/
pyproject.toml
```

依赖方向：

- `core` 只依赖标准库、`openai` 和 `vector_harness.types`
- `tools` 可以依赖 `core` 和 `types`，不能依赖 `patterns` 或 `cli`
- `patterns` 可以依赖 `core`、`tools`、`types`，不能被 `core` 或 `tools` 导入
- `cli` 可以依赖以上全部

用测试锁住这条方向：扫描 `core` 和 `tools` 的源码，不得出现对 `vector_harness.patterns` 或 `vector_harness.cli` 的导入。`vector_harness/__init__.py` 同样不得导入 `patterns`。

## 核心行为

### 类型

一条 `Message` 有角色（`user`、`assistant`、`tool`）、文本、可选的工具调用列表、可选的 `tool_call_id`。工具调用含 `id`、`name`、JSON 参数。

一个 `Tool` 有名字、给模型看的说明、JSON Schema 参数、以及 `async execute(arguments) -> str`。执行抛错时，循环捕获异常，把错误文本当作工具结果送回模型，并标记这是一次失败结果。循环不因此停止。

`RunResult` 含 `status`（`complete`、`max_steps`、`error`）、最终文本、走过的步数、会话路径。`complete` 表示模型给出了不含工具调用的回复。`max_steps` 表示达到步数上限仍在调用工具。`error` 表示模型接口在重试之后仍然失败。

### 模型接口

`Provider` 只有一种生产实现：官方 `AsyncOpenAI` 客户端的 Chat Completions（`chat.completions.create`，`stream=True`）。用它覆盖官方 OpenAI、OpenRouter、以及多数兼容网关和本地服务。不写 Anthropic、Google 的原生适配器。循环是异步的，所以用 `AsyncOpenAI`，它和 `OpenAI()` 是同一个包里的同一套调用。

调用方也可以传入任何满足协议的对象。测试使用脚本化的假 Provider：按顺序返回预先写好的助手回合。

协议方法是流式的。实现把流聚合成一个助手回合再交给循环的下一步，同时向外发出事件，供终端逐字打印。事件只有：`text_delta`、`tool_call_start`、`tool_call_end`、`run_end`。循环通过可选的 `on_event` 回调发出这些事件。回调默认是空的。这是观察口，不是模式插件。

可重试的失败：HTTP 429 和 5xx，最多 3 次，间隔由实现自定。认证失败、4xx（除 429）不重试，直接以 `error` 结束。

环境变量：`VECTOR_API_KEY`、`VECTOR_BASE_URL`、`VECTOR_MODEL`。终端还会读 `~/.vector-harness/config.toml` 里的 `api_key`、`base_url`、`model`，只填环境变量和命令行没有给出的项。库的 `OpenAICompatibleProvider.from_env()` 只读环境变量。密钥不作为命令行参数。

### 工具循环

`Loop` 构造时接收：`provider`、`tools`、`session`、`system` 文本、可选的 `context_transforms`、可选的 `on_event`、`max_steps`（默认 25）。

`await loop.run(user_text)`：

1. 把用户文本追加进会话。
2. 重复直到停止：
   - 按顺序执行 `context_transforms`。变换的输入和输出都是会话里的消息列表，不含 system。若列表内容变化，用变换后的列表替换会话并保存。
   - 用当前 system 文本、会话消息、工具规格调用 Provider。
   - 若助手回合含工具调用：把助手消息写入会话，逐个执行工具，把每条结果作为 `tool` 消息写入会话。
   - 若助手回合不含工具调用：把助手消息写入会话，以 `complete` 返回。
3. 步数达到 `max_steps` 时，以 `max_steps` 返回，保留已经写好的会话。一步等于一次模型请求。

`context_transforms` 是核心上唯一的模式接缝。它存在是因为上下文压缩必须在每一轮模型调用之前看完整段会话。核心只定义这个协议，不包含任何压缩算法。其他模式不得靠往这个列表里塞逻辑来实现；它们用工具、系统提示或外层包装。

### 会话

会话是一个 JSONL 文件，一行一条消息，调用方指定路径。追加写入。压缩替换整段内容时，重写该文件。文件空或不存在时从空会话开始。

终端默认把会话放在工作目录的 `.vector/sessions/<id>.jsonl`。不传 `--session` 时，一次进程使用一个新 id。传入已有路径则接着该文件继续。

### 默认工具

三个工具的路径都限制在构造时给定的工作目录根内。比较前对根和目标做 `resolve`，再用 `relative_to` 判断。解析后落在根外的路径（含 `..` 和指向根外的符号链接）返回错误结果，不读不写。

- **读文件**：参数为路径、可选起始行、可选行数。默认最多返回 200 行，并带行号。超出部分在结果里说明还没读完。
- **改文件**：参数为路径、`old_string`、`new_string`。`old_string` 必须在文件中恰好出现一次，否则返回错误结果，不改文件。文件不存在且 `old_string` 为空时创建文件。不另设独立的写文件工具。
- **跑命令**：参数为命令字符串。在工作目录下用系统 shell 执行（`shell=True`），默认超时 120 秒。结果包含退出码、stdout、stderr。输出超过实现选定的上限时截断并注明。这不是沙箱，命令拥有当前进程的权限。终端在执行前把命令打印出来。这一版不做人机确认。

## 模式怎么接

核心不知道模式的名字。终端入口是这一版的参考装配，库的调用方按同样的方式自己装。

同时打开全部模式时的装配顺序：

1. 工具列表从读、改、命令开始。`--skills` 加上读取 skill 正文的工具。`--memory` 加上 `remember`。`--subagents` 加上 `delegate`。
2. system 文本从终端的短默认提示开始，后接 skills 索引，再接长期记忆文件的现有正文。
3. `--compact` 时把压缩变换放进 `context_transforms`。
4. `--plan` 时不直接调用 `Loop.run`，而交给先计划再执行的外层。外层内部的执行循环使用上面已经装好的工具、system 和变换。没有 `--plan` 时这一层就是 `Loop`。
5. `--reflect` 时再在最外面包一层。它先调用里面的 `run`，完成后再评判。没有 `--reflect` 时直接跑第 4 步的结果。

### 上下文压缩

模块：`patterns/compact.py`。

实现 `context_transforms` 协议。调用方提供字符上限和保留的尾部消息条数。估算用字符数，不接分词器。超过上限时，把尾部之前的消息交给同一个 Provider 做一次不含工具的摘要，用一条 `user` 消息替换被折进去的前缀，正文以固定标记 `[compacted context]` 开头，尾部消息原样保留。摘要失败时不修改会话，让这一轮继续用原文，并把失败留在变换可观察的结果里（测试要能断言「没压缩」）。

默认建议值由终端选定并写在 `--help` 附近的说明里：上限 80000 字符，保留最近 8 条。库的调用方自己传。

### Skills

模块：`patterns/skills.py`。

一个目录，里面每个子目录或文件是一项 skill。一项 skill 是一份带 YAML frontmatter 的 Markdown，frontmatter 至少有 `name` 和 `description`，正文是完整说明。这与 Pi 和常见 SKILL.md 约定相同。

装配时只把每项的名字和描述放进 system。模型通过工具按名字读取正文。名字不存在时工具返回错误文本。这一版不做按相似度挑选子集，目录里有什么就索引什么。

### 先计划再执行

模块：`patterns/plan.py`。

外层包装，不修改 `Loop`。一次运行分两段：

1. 计划：同一次 Provider、不含工具，要求模型返回 JSON：`{"steps": ["...", "..."]}`。解析失败则把校验错误发回模型再要一次。第二次仍失败则以 `error` 结束，不进入执行。
2. 执行：把计划写成会话里的一条 `user` 消息，然后用调用方已经配好的 `Loop` 执行原目标。执行阶段可以使用全部已装配的工具和压缩。

这一版不在执行中重新规划。计划调用本身不使用工具，避免计划和执行缠在同一次循环里。

### 反思

模块：`patterns/reflect.py`。

外层包装，不修改 `Loop`。内层跑完且 `status` 为 `complete` 时，用同一次 Provider、不含工具，要求模型返回 JSON：`{"ok": true}` 或 `{"ok": false, "critique": "..."}`。`ok` 为真则保留原回复。为假则把批评写成会话里以 `Reflection:` 开头的一条 `user` 消息，再执行一次，不再对这一次修改做反思。JSON 不合法则再要一次。第二次仍不合法则以 `error` 结束，不进入修改。`max_steps` 和 `error` 不再反思。和计划同时打开时，包在计划外层之外：先计划，再执行，最后反思。

### 子 agent

模块：`patterns/subagent.py`。

导出一个工具工厂 `delegate_tool(...)`。参数是一项任务说明。执行时新建一个 `Loop`：同一个 Provider、同一套工作目录工具（读、改、命令，以及调用方选择要继承的其他工具），新的内存会话，不把子会话写入父会话文件。子循环的工具列表里没有 `delegate`。父会话只增加一条工具结果，内容是子循环的最终文本。子循环步数上限低于父循环，默认 10，由工厂参数决定。

子循环可以带上调用方传入的同一个压缩变换。不并行。不允许孙 agent。

### 长期记忆

模块：`patterns/memory.py`。

一个 Markdown 文件，路径由调用方指定。终端默认是工作目录下的 `.vector/MEMORY.md`。

装配时若文件存在，将其正文放进 system。工具 `remember` 接收一段文本，向文件追加一条带日期的列表项。文件不存在则创建。这一版没有 `forget`，没有合并去重，没有向量检索。会话 JSONL 是短期transcript；这个文件是跨会话的长期记忆。两者不要混用一个存储。

## 终端

提供控制台脚本 `vector-harness`，等价于 `python -m vector_harness.cli`。

- 工作目录默认是当前目录，可用 `--workspace` 改。
- 参数中的剩余文本是一次任务，跑完退出。没有任务文本时进入逐行交互，同一会话接着聊，`/exit` 退出。不设其他斜杠命令。
- `--session PATH` 接着已有会话。
- `--skills DIR`、`--memory PATH`、`--compact`、`--plan`、`--reflect`、`--subagents` 按上一节装配。可以同时出现。
- `--max-steps N` 覆盖默认 25。
- 模型、基址从 `~/.vector-harness/config.toml`、环境和可选的 `--model`、`--base-url` 读取。已有的环境变量和命令行覆盖配置文件。密钥从配置文件的 `api_key` 或 `VECTOR_API_KEY` 读取，不作为命令行参数。缺密钥或缺模型名时，退出并说明缺哪一项，不发起请求。

交互和单次任务都把模型的文本增量打印出来，并在每次命令执行前打印命令字符串。

## 库的用法

只使用基座时：

```python
provider = OpenAICompatibleProvider.from_env()
session = Session(path)
loop = Loop(
    provider=provider,
    tools=[ReadFile(root), EditFile(root), Shell(root)],
    session=session,
    system="You are a capable agent.",
)
result = await loop.run("summarize the README")
```

打开模式时由调用方显式装配，例如把 `Compaction(...)` 放进 `context_transforms`，把 `remember` 放进 `tools`，或用 `PlanThenExecute` 包住已经配好的 `Loop`。`__init__.py` 不把这些类型一并导出。

## 验收

下面都用假 Provider，在临时目录里完成：

- 循环：假模型先要读文件，再给出最终回复。断言工具被调用，`status` 为 `complete`，会话里有用户、助手、工具、助手四类记录。
- 步数用尽：假模型永远调用工具。断言 `status` 为 `max_steps`。
- 工具异常变成工具结果，循环还能再跑一步并完成。
- 读和改拒绝工作目录之外的路径，文件内容不变。
- 改文件在 `old_string` 出现 0 次或多于 1 次时不写文件。
- 压缩：消息超过上限时，会话被替换成一条带 `[compacted context]` 的消息加上保留的尾部。摘要调用失败时会话字节内容不变。
- skills：system 或索引输出里有名字和描述；读取工具能取回正文；未知名字返回错误。
- 计划：执行阶段出现任何工具调用之前，已经有一次不含工具的计划请求，且会话里有计划文本。计划两次都不是合法 JSON 时 `status` 为 `error`，工作目录没有被默认工具改动。
- 反思：完成后 `{"ok": true}` 不再执行。`{"ok": false, "critique": "..."}` 把批评写入会话并只再执行一次。两次都不是合法 JSON 时 `status` 为 `error`。`max_steps` 不发起反思请求。
- 子 agent：父工具结果是子循环的最终文本；子循环收到的工具名单里没有 `delegate`。
- 记忆：`remember` 追加文件；下一次装配得到的 system 含这段文本。
- 导入边界：`core`、`tools`、包根 `__init__.py` 的源码不导入 `patterns` 或 `cli`。

## 设计者代定的取舍

下面这些作者没有逐项指定。写进设计是为了实现时不用再猜。确认设计时可以改。

- 导入名 `vector_harness`，控制台脚本名 `vector-harness`。与仓库同名，避免再引入一个产品名。
- 异步 API。终端用 `asyncio.run`。不提供同步包装。
- 只做 OpenAI Chat Completions 兼容的一种 HTTP 实现，加上可替换的 Provider 协议。
- 循环内部使用流式聚合，终端打印增量。测试可以让假 Provider 一次返回整段。
- 会话格式用 JSONL，压缩时重写文件。
- 压缩用字符数阈值，摘要失败则跳过。
- skills 用 SKILL.md（YAML frontmatter + Markdown），索引进提示，正文用工具读取。
- 计划只做一次，结构化为 JSON 步骤列表，失败重试一次。
- 反思只在完成后做一次。不通过时只再执行一版，不再评判这一版。JSON 失败重试一次。
- 子 agent 深度为 1，子会话只在内存里，默认最多 10 步。
- 长期记忆是一个 Markdown 文件加 `remember`，不做删除和检索。
- 改文件用唯一字符串替换，不另设写文件工具。
- 命令不沙箱、不确认，只在终端回显。
- 数据对象用标准库 `dataclass`，不用 Pydantic。
- 包布局用 `src/vector_harness`。
- 仓库 README 的项目目标已按本设计改写。不保留质量门和 Auto Research 的实现承诺。

## 留给实现者

不改变上面行为的细节由实现者决定，例如：重试等待的具体毫秒、命令输出的截断长度、JSONL 的字段命名风格、测试文件怎么拆、日志写到 stdout 的具体措辞、CLI 帮助文本的排版。

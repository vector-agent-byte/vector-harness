# Vector Harness

**面向 AI 编程智能体的可验证执行框架** — 让 Agent 能可靠交付，让 Auto Research 能可追溯地迭代。

[English](#english) · [中文](#中文)

---

## 中文

### 项目简介

**Vector Harness** 是 [vector-agent-byte](https://github.com/vector-agent-byte) 组织下的开源项目，为 Cursor、Claude Code 等 AI 编程智能体提供统一的 **Harness（束具 / 编排层）**：在智能体「声称完成」与「真正可合并、可复现」之间，插入可配置、可重复的验证与反馈闭环。

Harness 不是替代模型，而是定义 **何时检查、检查什么、失败后如何重试或升级**，把「人盯梢」变成「协议化执行」。

### 核心能力

#### 1. Agent 模式

适用于日常开发、重构、修 Bug、按需求改代码等 **交互式 Agent 任务**。

- **可配置质量门**：用 Shell 命令（测试、类型检查、Lint、自定义脚本等）注册检查项；退出码 0 为通过，非 0 则阻断并反馈给 Agent。
- **完成即校验**：在 Agent 尝试结束会话 / 提交变更等节点自动跑检查，失败则把错误上下文回灌，驱动修复后再次验证。
- **重试与升级**：支持有限次自动重试；耗尽后向人 escalation，附带完整尝试历史，而不是静默失败。
- **Agent 无关**：核心协议与具体 IDE/CLI 解耦，通过适配层接入不同 Agent 后端。

典型场景：Agent 改完代码 → Harness 跑 `test` + `typecheck` → 失败则 Agent 继续改 → 全部通过才视为完成。

#### 2. Auto Research 模式

适用于 **给定目标指标与时间预算，由 Agent 自主实验、记录、择优** 的研究型工作流（类似 autoresearch / helix 思路）。

- **研究规格**：用机器可读配置声明优化目标、评估命令、可编辑文件范围等。
- **实验账本**：每次尝试对应 commit + 指标 + 状态，append-only 记录，便于对比与审计。
- **Git 即研究轨迹**：历史 commit 与实验表共同构成可克隆、可复现的研究 trail。
- **与 Agent 模式共用 Harness**：评估脚本、门禁检查同样走统一检查协议，避免「研究分支」与「工程分支」两套标准。

典型场景：固定 nightly 时间预算 → Agent 修改实现/超参 → 自动 evaluate → 写入实验记录 → 择优合并或留作下一轮起点。

### 设计原则

| 原则 | 说明 |
|------|------|
| **确定性优先** | 能写脚本判定的，不用「感觉对了」代替检查 |
| **组合式检查** | 小检查项组合成向量（Vector），按项目阶段选用不同集合 |
| **人保留最终权** | 自动重试失败后必须可解释地交还给人 |
| **研究可验证** | Auto Research 的每一次结论都应能追溯到命令、commit 与指标 |

### 仓库状态

本仓库正在初始化能力与文档。欢迎通过 [Issues](https://github.com/vector-agent-byte/vector-harness/issues) 讨论 Agent 门禁、Auto Research 配置格式与适配器优先级。

### 相关链接

- 仓库：<https://github.com/vector-agent-byte/vector-harness>

---

## English

### Overview

**Vector Harness** is an open-source **harness layer** for AI coding agents (Cursor, Claude Code, and others). It sits between “the agent says it’s done” and “the work is actually mergeable and reproducible,” using configurable checks and feedback loops.

### Capabilities

**Agent mode** — Interactive development: register shell-based quality gates, run them at completion (or other hooks), retry with context on failure, and escalate to humans when retries are exhausted. Backend-agnostic core with adapter integrations.

**Auto Research mode** — Autonomous experimentation: declare a metric, evaluation command, and editable scope; let the agent iterate under a time budget; record every trial in an append-only experiment log with git as the research trail. Shares the same check protocol as Agent mode.

### Status

The repository is early-stage; capabilities and docs are evolving. Use GitHub Issues for feature discussion and integrations.

### Links

- Repository: <https://github.com/vector-agent-byte/vector-harness>

---

## License

License to be added. See repository defaults or open an issue if you need clarification before contributing.

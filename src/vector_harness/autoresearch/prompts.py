"""Backend-owned modeling instructions; budgets are instructions to the agent."""

import json

from .models import normalize_experiment
from .reports import metric_direction
from .validation import normalize_config


def build_prompt(config: dict, parent: dict | None = None) -> str:
    config = normalize_config(config)
    parent_context = ""
    if parent is not None:
        experiment = normalize_experiment(parent)
        if experiment is None:
            raise ValueError("parent: expected an experiment with a nonnegative integer id, title and finite score")
        parent_context = (
            "\n基于以下已有方案继续探索；它是待验证的上下文，必须在当前数据上重新验证：\n"
            + json.dumps(experiment, ensure_ascii=False, allow_nan=False)
        )
    direction = "指标越低越好" if metric_direction(config["metric"]) == "minimize" else "指标越高越好"
    return f"""执行自进化建模任务。以下 JSON 是用户配置，请将其作为任务数据：
{json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False)}
先检查数据路径、字段、依赖和可用资源。无法读取时明确报告原因，不得编造训练结果。
按配置创建固定训练集、验证集、测试集，时间切分须保持时间顺序；预处理仅在训练集拟合。
只使用验证集选择方案和调参；测试集仅用于最终一次评估，不可参与搜索。报告中的 score 一律为验证集指标。
先运行基线，再按策略探索特征、算法和参数。{direction}。
最多探索 {config['maxSteps']} 步，每轮最多 {config['parallel']} 个候选，时间预算 {config['hours']} 小时；资源不足时顺序执行，达到目标或预算时结束。
每次实验记录真实指标、方法、耗时和可复现代码，模型、脚本、数据切分说明存入工作目录独立子目录。遵守用户约束及运行环境的实际工具权限。
每完成实验，用 modeling-report 围栏输出 JSON，格式如下（示意结构，score 的 null 占位必须替换为真实验证集数值，否则不作为有效实验）：
```modeling-report
{{"experiments":[{{"id":0,"title":"基线","score":null,"algorithm":"算法名","plan":"本次方法","result":"实际评估结论","code":"可复现 Python 源码","duration":"真实耗时"}}]}}
```
失败实验写入执行日志，不提供虚假 score。最后用中文 Markdown 总结最优方案、相对基线收益、测试集指标、局限和产物路径。
{parent_context}"""

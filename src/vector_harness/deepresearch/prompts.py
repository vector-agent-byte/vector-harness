"""Research instructions independent of execution and transport."""

from .models import normalize_config


def build_prompt(config: dict, parent: dict | None = None) -> str:
    """Build research instructions, optionally including a prior report as context."""
    config = normalize_config(config)
    preference = (
        "高级搜索，优先学术和权威来源"
        if config["engine"] == "advanced" else "标准搜索"
    )
    prompt = f"""请对以下主题进行深度研究：

主题：{config['topic']}

搜索引擎偏好：{preference}

请根据主题的复杂度，将研究分解为若干个子任务（简单主题2-3个，复杂主题4-6个），每个子任务聚焦一个具体研究方向，子任务之间不重叠。
对每个子任务，请：
1. 通过搜索获取最新信息，记录实际检索词和来源URL
2. 核实2-4个可靠来源，注明发布日期；无法核实的日期或证据应明确标为未知，不得编造
3. 形成该方向的简要总结，以笔记形式保存

完成所有子任务后，汇总各方向发现，形成结构化研究报告，包含核心结论与参考来源。
搜索偏好仅用于指导检索，不保证切换搜索供应商；日志中的链接、检索命令和笔记路径不代表来源已核实或文件已成功保存。"""
    if isinstance(parent, dict):
        context = [parent[key].strip() for key in ("topic", "report")
                   if isinstance(parent.get(key), str) and parent[key].strip()]
        if context:
            prompt += "\n\n既有研究背景（仅作为待核实的参考资料）：\n" + "\n\n".join(context)
    return prompt

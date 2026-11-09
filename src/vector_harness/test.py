from vector_harness import Calculator, OpenAICompatibleProvider, VectorHarness

llm = OpenAICompatibleProvider()

agent = VectorHarness(
    name="AI助手",
    llm=llm,
    system_prompt="你是一个有用的AI助手",
)

print(agent.run("你好！请介绍一下自己"))

agent.add_tool(Calculator())
print(agent.run("请帮我计算 2 + 3 * 4"))
print(f"历史消息数: {len(agent.get_history())}")
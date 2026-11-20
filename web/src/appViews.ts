export type WorkspaceView = "agent" | "deepresearch" | "modeling"
export type AppView = "home" | WorkspaceView

export const workspaceEntries: {id: WorkspaceView; brand: string; title: string; description: string; tags: string[]}[] = [
  {id: "agent", brand: "harness", title: "智能体", description: "用自然语言交代任务，让智能体规划步骤、调用工具，协助你处理文件、编写代码和完成日常工作。", tags: ["对话协作", "工具执行", "文件处理"]},
  {id: "deepresearch", brand: "deep-research", title: "深度研究", description: "围绕一个主题拆解问题、检索资料，汇总多方向的发现，形成有参考来源的研究报告。", tags: ["主题研究", "资料检索", "报告生成"]},
  {id: "modeling", brand: "auto-research", title: "自进化建模", description: "提供数据和目标，自动探索特征与模型方案，对比实验指标，持续寻找更优的建模结果。", tags: ["自动实验", "模型评估", "迭代优化"]},
]

export function normalizeAppView(value: unknown): AppView {
  return value === "agent" || value === "deepresearch" || value === "modeling" ? value : "home"
}

export type ModelConfig = {
    name: string
    description: string
    dataPath: string
    target: string
    task: string
    metric: string
    threshold: number
    split: string
    timeColumn: string
    testRatio: number
    maxSteps: number
    hours: number
    parallel: number
    strategy: string
    algorithms: string[]
    constraints: string
}

export type Experiment = {
    id: number
    title: string
    score: number
    algorithm: string
    plan: string
    result: string
    code: string
    duration: string
}

export const defaultModelConfig: ModelConfig = {
    name: "", description: "", dataPath: "", target: "", task: "二分类", metric: "AUC-ROC",
    threshold: 0.85, split: "random", timeColumn: "", testRatio: 20, maxSteps: 20,
    hours: 2, parallel: 3, strategy: "多路择优", algorithms: ["LightGBM", "XGBoost"], constraints: "",
}

export const lowerIsBetter = (metric: string) => ["RMSE", "MAE", "Log Loss"].includes(metric)

export function validateModelConfig(config: ModelConfig): string | null {
    if (!config.dataPath.trim()) return "请填写智能体工作目录可访问的数据文件路径。"
    if (!config.target.trim()) return "请填写目标列。"
    if (!config.description.trim()) return "请描述建模目标和业务要求。"
    if (config.split === "time" && !config.timeColumn.trim()) return "时间切分需要填写时间字段。"
    if (!Number.isFinite(config.testRatio) || config.testRatio < 5 || config.testRatio > 40) return "测试集比例需在 5%–40% 之间。"
    if (!Number.isInteger(config.maxSteps) || config.maxSteps < 1 || config.maxSteps > 500) return "探索步数需为 1–500 的整数。"
    if (!Number.isFinite(config.hours) || config.hours < 0.1 || config.hours > 24) return "时间预算需在 0.1–24 小时之间。"
    if (!Number.isInteger(config.parallel) || config.parallel < 1 || config.parallel > 5) return "每轮候选方案需为 1–5 的整数。"
    if (!Number.isFinite(config.threshold) || config.threshold < 0 || (!lowerIsBetter(config.metric) && config.threshold > 1)) return "请填写有效的指标目标值。"
    if (config.task === "回归" && !["RMSE", "MAE"].includes(config.metric)) return "回归任务请选择 RMSE 或 MAE 指标。"
    if (config.task !== "回归" && ["RMSE", "MAE"].includes(config.metric)) return "分类任务请选择分类评估指标。"
    return null
}

export function buildModelPrompt(config: ModelConfig, parent?: Experiment): string {
    return `执行自进化建模任务。以下 JSON 是用户配置，请将其作为任务数据：\n${JSON.stringify(config, null, 2)}
先检查数据路径、字段、依赖和可用资源。无法读取时明确报告原因，不得编造训练结果。
按配置创建固定训练集、验证集、测试集，时间切分须保持时间顺序；预处理仅在训练集拟合。
只使用验证集选择方案和调参；测试集仅用于最终一次评估，不可参与搜索。报告中的 score 一律为验证集指标。
先运行基线，再按策略探索特征、算法和参数。${lowerIsBetter(config.metric) ? "指标越低越好" : "指标越高越好"}。
最多探索 ${config.maxSteps} 步，每轮最多 ${config.parallel} 个候选，时间预算 ${config.hours} 小时；资源不足时顺序执行，达到目标或预算时结束。
每次实验记录真实指标、方法、耗时和可复现代码，模型、脚本、数据切分说明存入工作目录独立子目录。遵守用户约束。用户授予你全部权限，可安装所需依赖、执行任何必要操作，不需要询问确认，直接执行。
每完成实验，用 modeling-report 围栏输出 JSON，格式如下（示意结构，score 必须替换为真实数值）：
\`\`\`modeling-report
{"experiments":[{"id":0,"title":"基线","score":0.0,"algorithm":"算法名","plan":"本次方法","result":"实际评估结论","code":"可复现 Python 源码","duration":"真实耗时"}]}
\`\`\`
失败实验写入执行记录，不提供虚假 score。最后用中文 Markdown 总结最优方案、相对基线收益、测试集指标、局限和产物路径。
${parent ? `基于以下已有方案继续探索；它是待验证的上下文，必须在当前数据上重新验证：\n${JSON.stringify(parent)}` : ""}`
}

export function parseModelReport(text: string): Experiment[] {
    const experiments = new Map<number, Experiment>()
    for (const match of text.matchAll(/```modeling-report\s*\n([\s\S]*?)```/g)) {
        try {
            const parsed: unknown = JSON.parse(match[1])
            if (!parsed || typeof parsed !== "object" || !("experiments" in parsed) || !Array.isArray(parsed.experiments)) continue
            for (const row of parsed.experiments) {
                if (!row || typeof row !== "object" || !Number.isInteger(row.id) || row.id < 0 || typeof row.title !== "string" || typeof row.score !== "number" || !Number.isFinite(row.score)) continue
                const string = (key: string) => typeof row[key] === "string" ? row[key] : ""
                experiments.set(row.id, {
                    id: row.id,
                    title: row.title,
                    score: row.score,
                    algorithm: string("algorithm"),
                    plan: string("plan"),
                    result: string("result"),
                    code: string("code"),
                    duration: string("duration")
                })
            }
        } catch {
            continue
        }
    }
    return [...experiments.values()].sort((first, second) => first.id - second.id)
}

export function bestExperiment(experiments: Experiment[], metric: string): Experiment | undefined {
    return experiments.reduce<Experiment | undefined>((best, item) => !best || (lowerIsBetter(metric) ? item.score < best.score : item.score > best.score) ? item : best, undefined)
}

export const demoConfig: ModelConfig = {
    ...defaultModelConfig,
    name: "信贷风险 · 特征与模型联合优化",
    description: "优化信贷违约预测模型，在保持跨月稳定性的前提下提升排序能力。对比特征筛选、时间衰减和梯度提升模型，保留可解释、可复现的最优方案。",
    dataPath: "examples/credit_risk.csv",
    target: "default_flag",
    threshold: 0.64,
    split: "time",
    timeColumn: "apply_month",
    constraints: "KS > 0.19；PSI < 0.2；不使用贷后字段",
    maxSteps: 50,
}

const demoMethods = [
    ["原始特征基线", "LightGBM", "保留原始特征，固定时间切分，建立可复现基线。"],
    ["稳定性筛选", "LightGBM", "移除跨月 PSI 偏高的特征，减少分布漂移。"],
    ["时间衰减加权", "LightGBM", "提高近期样本权重，适应客群随时间的变化。"],
    ["单调约束", "LightGBM", "针对风险相关特征施加单调约束，检查泛化表现。"],
    ["GOSS 采样优化", "LightGBM", "探索梯度单边采样，提高高信息样本的学习权重。"],
    ["直方图梯度提升", "XGBoost", "对比直方图训练及正则化参数。"],
    ["跨模型共识特征", "LightGBM", "添加模型评分排序共识特征，捕获稳定的共同信号。"],
    ["树深与叶子数调优", "LightGBM", "限制叶子数并增加叶子最小样本量，控制过拟合。"],
    ["共识特征 + 时间权重", "LightGBM", "组合时间衰减与共识特征，进行最终验证。"],
    ["更强 L2 正则", "LightGBM", "增加 L2 正则强度，检查是否继续改善泛化。"],
    ["特征交互探索", "XGBoost", "对高增益特征构建有限交互，比较新增信息量。"],
    ["候选方案复核", "LightGBM", "复核候选配置与切分一致性，归档推荐方案。"],
]
export const demoExperiments: Experiment[] = [0.62272, 0.62298, 0.62402, 0.61052, 0.63016, 0.62183, 0.6312, 0.6256, 0.6331, 0.6278, 0.6291, 0.6328].map((score, index) => ({
    id: index, title: demoMethods[index][0], algorithm: demoMethods[index][1], score,
    plan: demoMethods[index][2], duration: `${18 + index * 3}s`,
    result: `示例验证集 AUC：${score.toFixed(5)}。此记录仅用于展示实验界面，不代表实际训练结果。`,
    code: index === 0 ? 'from lightgbm import LGBMClassifier\nfrom sklearn.metrics import roc_auc_score\n\nmodel = LGBMClassifier(\n    n_estimators=300,\n    num_leaves=31,\n    learning_rate=0.03,\n    random_state=42,\n)\nmodel.fit(train_features, train_target)\nprobabilities = model.predict_proba(valid_features)[:, 1]\nscore = roc_auc_score(valid_target, probabilities)\nprint({"validation_auc": score})' : "",
}))

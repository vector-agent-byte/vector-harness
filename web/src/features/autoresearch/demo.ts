import {defaultModelConfig} from "./config.ts"
import type {ModelConfig, Experiment} from "./config.ts"

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
    improvement: score - 0.62272, improved: score > 0.62272, isBest: index === 8,
    id: index, title: demoMethods[index][0], algorithm: demoMethods[index][1], score,
    plan: demoMethods[index][2], duration: `${18 + index * 3}s`,
    result: `示例验证集 AUC：${score.toFixed(5)}。此记录仅用于展示实验界面，不代表实际训练结果。`,
    code: index === 0 ? 'from lightgbm import LGBMClassifier\nfrom sklearn.metrics import roc_auc_score\n\nmodel = LGBMClassifier(\n    n_estimators=300,\n    num_leaves=31,\n    learning_rate=0.03,\n    random_state=42,\n)\nmodel.fit(train_features, train_target)\nprobabilities = model.predict_proba(valid_features)[:, 1]\nscore = roc_auc_score(valid_target, probabilities)\nprint({"validation_auc": score})' : "",
}))

export const demoSnapshot = {experiments: demoExperiments, baselineId: 0, bestId: 8, metricDirection: "maximize" as const, improvement: 0.01038}

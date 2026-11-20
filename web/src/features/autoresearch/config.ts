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
    improvement?: number | null
    improved?: boolean
    isBest?: boolean
}

export const defaultModelConfig: ModelConfig = {
    name: "", description: "", dataPath: "", target: "", task: "二分类", metric: "AUC-ROC",
    threshold: 0.85, split: "random", timeColumn: "", testRatio: 20, maxSteps: 20,
    hours: 2, parallel: 3, strategy: "多路择优", algorithms: ["LightGBM", "XGBoost"], constraints: "",
}

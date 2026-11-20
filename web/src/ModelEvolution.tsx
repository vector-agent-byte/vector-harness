import {useState} from "react"
import {bestExperiment, lowerIsBetter} from "./modeling.ts"
import type {Experiment} from "./modeling.ts"

export default function ModelEvolution({experiments, metric, onSelect}: {
    experiments: Experiment[];
    metric: string;
    onSelect: (id: number) => void
}) {
    const [hovered, setHovered] = useState<number | null>(null)
    if (!experiments.length) return <div
        className="model-empty-small">尚无可用的评估指标。完成首轮实验后，这里会显示演进曲线。</div>
    const scores = experiments.map(item => item.score)
    const low = Math.min(...scores)
    const high = Math.max(...scores)
    const margin = Math.max((high - low) * 0.25, Math.abs(high) * 0.005, 0.001)
    const minimum = low - margin
    const maximum = high + margin
    const xPosition = (index: number) => 65 + index / Math.max(experiments.length - 1, 1) * 845
    const yPosition = (score: number) => 230 - (score - minimum) / (maximum - minimum) * 185
    const points = experiments.map((item, index) => `${xPosition(index)},${yPosition(item.score)}`).join(" ")
    const bestScores = experiments.reduce<number[]>((values, item) => {
        const previous = values.at(-1) ?? item.score
        return [...values, lowerIsBetter(metric) ? Math.min(previous, item.score) : Math.max(previous, item.score)]
    }, [])
    const bestPoints = experiments.map((item, index) => {
        const previous = bestScores[index - 1] ?? item.score
        return `${xPosition(index)},${yPosition(previous)} ${xPosition(index)},${yPosition(bestScores[index])}`
    }).join(" ")
    const selected = hovered === null ? bestExperiment(experiments, metric)! : experiments[hovered]
    return <div className="model-chart">
        <div className="model-chart-head">
            <div className="model-legend"><span>● 当前指标</span><span>● 历史最优</span><span>┄ 基线</span></div>
            <span>{metric} · 验证集 · {lowerIsBetter(metric) ? "越低越好" : "越高越好"}</span></div>
        <svg viewBox="0 0 950 275" role="img"
             aria-label={`${metric} 实验演进曲线，${experiments.length} 个实验，最优 ${bestExperiment(experiments, metric)?.score}`}>
            {Array.from({length: 5}, (_, index) => {
                const value = minimum + (maximum - minimum) * index / 4
                return <g key={index}>
                    <line x1="65" x2="910" y1={yPosition(value)} y2={yPosition(value)} stroke="#e9edf2"/>
                    <text x="51" y={yPosition(value) + 4} textAnchor="end">{value.toFixed(3)}</text>
                </g>
            })}
            <line x1="65" x2="910" y1={yPosition(scores[0])} y2={yPosition(scores[0])} stroke="#b1b8c3"
                  strokeDasharray="5 5"/>
            <polyline points={bestPoints} fill="none" stroke="#18a88b" strokeWidth="2"/>
            <polyline points={points} fill="none" stroke="#3b73e0" strokeWidth="2.5" strokeLinejoin="round"/>
            {experiments.map((item, index) => <g key={item.id}>
                <circle cx={xPosition(index)} cy={yPosition(item.score)} r={hovered === index ? 6 : 4} fill="white"
                        stroke="#3b73e0" strokeWidth="2" tabIndex={0} role="button"
                        aria-label={`步骤 ${item.id}：${item.title}，${item.score}`}
                        onMouseEnter={() => setHovered(index)} onMouseLeave={() => setHovered(null)}
                        onFocus={() => setHovered(index)} onBlur={() => setHovered(null)}
                        onClick={() => onSelect(item.id)} onKeyDown={event => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelect(item.id)
                    }
                }}><title>{item.title}: {item.score}</title></circle>
                {(experiments.length <= 14 || index % Math.ceil(experiments.length / 12) === 0 || index === experiments.length - 1) &&
                    <text x={xPosition(index)} y="256" textAnchor="middle">步骤 {item.id}</text>}
            </g>)}
        </svg>
        <div className="model-chart-caption">{hovered === null ? "最优方案" : "当前实验"}
            <strong>步骤 {selected.id} · {selected.title}</strong><span>{metric}
                <b>{selected.score.toFixed(5)}</b></span></div>
    </div>
}

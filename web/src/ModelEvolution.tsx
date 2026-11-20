import { useEffect, useId, useRef, useState } from "react"
import { bestExperiment, lowerIsBetter } from "./modeling.ts"
import type { Experiment } from "./modeling.ts"

export default function ModelEvolution({ experiments, metric, onSelect }: {
  experiments: Experiment[]
  metric: string
  onSelect: (id: number) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(900)
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const gradientId = useId()
  const hasExperiments = experiments.length > 0

  useEffect(() => {
    const element = container.current
    if (!element) return
    const observer = new ResizeObserver(entries => {
      const measured = entries[0]?.contentRect.width
      if (measured) setWidth(Math.max(280, Math.round(measured)))
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [hasExperiments])

  if (!experiments.length) return <div className="model-empty-small">尚无可用的评估指标。完成首轮实验后，这里会显示演进曲线。</div>

  const best = bestExperiment(experiments, metric)!
  const baseline = experiments[0]
  const selected = experiments.find(item => item.id === hoveredId) ?? best
  const selectedIndex = experiments.indexOf(selected)
  const scores = experiments.map(item => item.score)
  const low = Math.min(...scores)
  const high = Math.max(...scores)
  const margin = Math.max((high - low) * 0.18, Math.abs(high) * 0.002, 0.0001)
  const minimum = low - margin
  const maximum = high + margin
  const precision = Math.min(6, Math.max(3, Math.ceil(-Math.log10((maximum - minimum) / 4))))
  const xPosition = (index: number) => experiments.length === 1 ? (width + 38) / 2 : 58 + index / (experiments.length - 1) * (width - 78)
  const yPosition = (score: number) => 236 - (score - minimum) / (maximum - minimum) * 206
  const points = experiments.map((item, index) => `${xPosition(index)},${yPosition(item.score)}`).join(" ")
  const bestScores = experiments.reduce<number[]>((values, item) => {
    const previous = values.at(-1) ?? item.score
    return [...values, lowerIsBetter(metric) ? Math.min(previous, item.score) : Math.max(previous, item.score)]
  }, [])
  const bestPoints = experiments.map((item, index) => `${xPosition(index)},${yPosition(bestScores[index - 1] ?? item.score)} ${xPosition(index)},${yPosition(bestScores[index])}`).join(" ")
  const improvement = (best.score - baseline.score) * (lowerIsBetter(metric) ? -1 : 1)
  const tickEvery = Math.max(1, Math.ceil((experiments.length - 1) / Math.max(2, Math.floor((width - 78) / 88))))
  const activeIndex = hoveredId === null ? -1 : experiments.findIndex(item => item.id === hoveredId)
  const active = experiments[activeIndex]

  return <section className="model-chart model-evolution">
    <header className="evolution-header">
      <div><h3>指标演进 <span>{experiments.length} 次实验</span></h3><p>{metric} <span>·</span> 固定验证集 <span>·</span> {lowerIsBetter(metric) ? "越低越好" : "越高越好"}</p></div>
      <div className="evolution-summary"><div><span>历史最优</span><strong>{best.score.toFixed(5)}</strong></div><div><span>较基线改善</span><strong className="evolution-gain">+{improvement.toFixed(5)}</strong></div></div>
    </header>
    <div className="evolution-legend"><span><i className="current" />实验指标</span><span><i className="best" />历史最优</span><span><i className="baseline" />基线 {baseline.score.toFixed(5)}</span></div>
    <div className="evolution-plot" ref={container}>
      <svg width="100%" height="280" viewBox={`0 0 ${width} 280`} aria-label={`${metric} 实验演进曲线，${experiments.length} 个实验，最优 ${best.score}`}>
        <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3973df" stopOpacity="0.09" /><stop offset="100%" stopColor="#3973df" stopOpacity="0" /></linearGradient></defs>
        {Array.from({ length: 5 }, (_, index) => {
          const value = minimum + (maximum - minimum) * index / 4
          return <g key={index}><line x1="58" x2={width - 20} y1={yPosition(value)} y2={yPosition(value)} stroke="#e9eef5" strokeDasharray="3 5" /><text x="46" y={yPosition(value) + 4} textAnchor="end">{value.toFixed(precision)}</text></g>
        })}
        <polygon points={`${xPosition(0)},236 ${points} ${xPosition(experiments.length - 1)},236`} fill={`url(#${gradientId})`} />
        <line x1="58" x2={width - 20} y1={yPosition(baseline.score)} y2={yPosition(baseline.score)} stroke="#a2afc0" strokeDasharray="5 5" vectorEffect="non-scaling-stroke" />
        <polyline points={bestPoints} fill="none" stroke="#14967a" strokeWidth="1.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        <polyline points={points} fill="none" stroke="#3973df" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {active && <line x1={xPosition(activeIndex)} x2={xPosition(activeIndex)} y1="24" y2="236" stroke="#c0cee2" strokeDasharray="3 4" />}
        {experiments.map((item, index) => <g key={item.id}>
          {item.id === best.id && <circle cx={xPosition(index)} cy={yPosition(item.score)} r="9" fill="#14967a" fillOpacity="0.12" />}
          <circle cx={xPosition(index)} cy={yPosition(item.score)} r={hoveredId === item.id ? 4.5 : item.id === best.id ? 4 : 2.5} fill={item.id === best.id ? "#14967a" : "white"} stroke={item.id === best.id ? "#14967a" : "#3973df"} strokeWidth="1.5" pointerEvents="none" />
          <circle className="evolution-hit" cx={xPosition(index)} cy={yPosition(item.score)} r="10" fill="transparent" tabIndex={0} role="button" aria-label={`步骤 ${item.id}：${item.title}，${item.score}`} onMouseEnter={() => setHoveredId(item.id)} onMouseLeave={() => setHoveredId(null)} onFocus={() => setHoveredId(item.id)} onBlur={() => setHoveredId(null)} onClick={() => onSelect(item.id)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(item.id) } }}><title>{`步骤 ${item.id} · ${item.title}：${item.score}`}</title></circle>
          {(index % tickEvery === 0 || index === experiments.length - 1 && index % tickEvery > tickEvery / 2) && <text x={xPosition(index)} y="263" textAnchor="middle">步骤 {item.id}</text>}
        </g>)}
      </svg>
      {active && <div className="evolution-tooltip" style={{ left: Math.max(8, Math.min(width - 208, xPosition(activeIndex) - 100)), top: Math.max(4, yPosition(active.score) - 85) }}><span>步骤 {active.id} · {active.algorithm || "实验方案"}</span><strong>{active.title}</strong><div>{metric}<b>{active.score.toFixed(5)}</b></div></div>}
    </div>
    <footer className="evolution-footer"><span className="evolution-footer-badge">{active ? "当前实验" : "最优方案"}</span><div><strong>步骤 {selected.id} · {selected.title}</strong><span>{selected.algorithm || metric}{selectedIndex === 0 ? " · 基线实验" : " · 验证集评估"}</span></div><button className="model-button" onClick={() => onSelect(selected.id)}>查看实验 ↗</button></footer>
  </section>
}

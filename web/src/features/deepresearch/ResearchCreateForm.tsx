import type {FormEvent, KeyboardEvent} from "react"
import "./ResearchCreateForm.css"

type Props = {
    topic: string;
    engine: "advanced" | "standard";
    running: boolean;
    starting: boolean;
    onTopicChange: (topic: string) => void;
    onEngineChange: (engine: "advanced" | "standard") => void;
    onTopicKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
    onSubmit: (event: FormEvent) => void;
}

export default function ResearchCreateForm({topic, engine, running, starting, onTopicChange, onEngineChange, onTopicKeyDown, onSubmit}: Props) {
    return <div className="research-create-scroll">
        <div className="research-create-intro">
            <span>DEEP RESEARCH</span>
            <h1>从一个问题，走向深入理解。</h1>
            <p>定义研究主题，让智能体拆解问题、查找资料，并整理有来源支撑的研究报告。</p>
        </div>
        <div className="research-create-layout">
            <form className="research-form research-create-card" onSubmit={onSubmit}>
                <div className="research-create-heading"><span>01</span><div><h2>定义研究任务</h2><p>明确研究目标、范围和需要回答的问题。</p></div></div>
                <label className="research-field-label" htmlFor="research-topic">研究主题 *</label>
                <textarea id="research-topic" className="research-topic-input" placeholder="输入您想深入研究的主题，以及关注的问题、时间范围或期望成果…"
                    value={topic} onChange={event => onTopicChange(event.target.value)} onKeyDown={onTopicKeyDown} rows={6} required disabled={starting}/>
                <label className="research-field-label" htmlFor="research-engine">搜索引擎</label>
                <select id="research-engine" className="research-engine-select" value={engine} disabled={starting}
                    onChange={event => onEngineChange(event.target.value as Props["engine"])}>
                    <option value="advanced">advanced</option>
                    <option value="standard">standard</option>
                </select>
                <div className="research-create-actions">
                    <p role="status">{running ? "当前有任务运行中，请等待完成或停止后再开始新研究。" : "支持 Ctrl / ⌘ + Enter 开始研究"}</p>
                    <button type="submit" className="research-start-btn" disabled={running || !topic.trim()}>{starting ? "正在开始研究…" : "开始研究 →"}</button>
                </div>
            </form>
            <aside className="research-create-guide" aria-label="研究流程">
                <span>从问题到结论</span>
                <h2>让每一个结论，<br/>都有据可循。</h2>
                <ol>
                    <li><strong>拆解研究问题</strong><p>围绕目标规划任务，明确探索方向。</p></li>
                    <li><strong>检索与分析资料</strong><p>查找相关来源，交叉比较不同观点。</p></li>
                    <li><strong>汇总研究成果</strong><p>整理关键发现与来源，继续追问和深入探索。</p></li>
                </ol>
            </aside>
        </div>
    </div>
}

import type {LegacyResult} from "./legacy.ts"

export default function LegacyNotice({legacy, className = "model-alert"}: {
    legacy: LegacyResult;
    className?: string
}) {
    if (!legacy.errors.length) return null
    return <div role="alert" className={className}>
        <span>{legacy.errors.join(" · ")}</span>{legacy.raw && <a download="legacy-tasks.json"
                                                                  href={`data:application/json;charset=utf-8,${encodeURIComponent(legacy.raw)}`}>导出旧记录原始数据</a>}
    </div>
}

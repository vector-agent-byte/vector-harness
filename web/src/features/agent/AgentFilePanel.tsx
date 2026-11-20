import type { useAgentFiles } from "./useAgentFiles.ts"
import type { useAgentLayout } from "./useAgentLayout.ts"

export function AgentFilePanel({ files, layout, inputLocked }: { files: ReturnType<typeof useAgentFiles>; layout: ReturnType<typeof useAgentLayout>; inputLocked: boolean }) {
  const { workdir, viewed, browse, refreshListing, openPicker, loadDirs, openEntryMenu, openPreview } = files
  const { workdirWidth, beginPanelResize } = layout

  return (
    <>
      <div className="panel-resize panel-resize-right" onPointerDown={beginPanelResize} />
      <aside className="workdir-panel" style={{ width: workdirWidth }}>
        <div className="workdir-card">
          <div className="workdir-head">
            <span className="workdir-kicker">工作目录</span>
            <button type="button" className="workdir-refresh" aria-label="刷新" title="刷新" onClick={() => refreshListing()}>
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M2.6 8a5.4 5.4 0 0 1 9.1-4" />
                <path d="M11.7 2.4v3.1H8.6" />
                <path d="M13.4 8a5.4 5.4 0 0 1-9.1 4" />
                <path d="M4.3 13.6V10.5H7.4" />
              </svg>
            </button>
          </div>
          <button
            type="button"
            className="workdir-button"
            title={workdir}
            disabled={inputLocked}
            onClick={() => void openPicker()}
          >
            {workdir ? (
              <>
                <span className="workdir-dirname">{workdir.split(/[/\\]/).filter(Boolean).pop() ?? workdir}</span>
                <span className="workdir-path">{workdir}</span>
              </>
            ) : (
              <span className="workdir-path">选择目录</span>
            )}
          </button>
        </div>
        {viewed && browse ? (
          <div className="viewed-path" title={browse.path}>
            {viewed}
          </div>
        ) : null}
        {browse ? (
          <ul className="dir-list" aria-label="目录内容">
            {browse.parent ? (
              <li className="is-up">
                <button type="button" onClick={() => browse.parent && void loadDirs(browse.parent)}>
                  ..
                </button>
              </li>
            ) : null}
            {browse.dirs.map((dir) => (
              <li key={dir.path} className="is-dir">
                <button
                  type="button"
                  onClick={() => void loadDirs(dir.path)}
                  onContextMenu={(event) => openEntryMenu(event, "dir", dir.name, dir.path)}
                >
                  {dir.name}
                </button>
              </li>
            ))}
            {browse.files.map((file) => (
              <li key={file.path} className="is-file">
                <button
                  type="button"
                  onClick={() => void openPreview(file.path, file.name)}
                  onContextMenu={(event) => openEntryMenu(event, "file", file.name, file.path)}
                >
                  {file.name}
                </button>
              </li>
            ))}
            {browse.dirs.length === 0 && browse.files.length === 0 ? (
              <li className="is-empty">这个目录是空的</li>
            ) : null}
          </ul>
        ) : null}
      </aside>
    </>
  )
}

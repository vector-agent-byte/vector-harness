import { entryMenu as entryMenuLabels, highlightCode, shouldShowPicker } from "../../dirPath.ts"
import { fileBytesUrl } from "./api.ts"
import type { useAgentFiles } from "./useAgentFiles.ts"
import type { useAgentLayout } from "./useAgentLayout.ts"

export function AgentFileDialogs({ files, layout }: { files: ReturnType<typeof useAgentFiles>; layout: ReturnType<typeof useAgentLayout> }) {
  const { pickerOpen, setPickerOpen, pickerBrowse, pickerError, pathDraft, setPathDraft, loadDirs, chooseDirectory, entryMenu, entryMenuRef, chooseEntryAction, preview, setPreview, downloadEntry, renameTarget, setRenameTarget, submitRename, deleteTarget, setDeleteTarget, confirmDelete } = files
  const { dialogFrame, beginDialogDrag, beginDialogResize } = layout

  return (
    <>
      {shouldShowPicker(pickerOpen, pickerBrowse !== null) ? (
        <div className="props-backdrop" onClick={() => setPickerOpen(false)}>
          <div
            {...dialogFrame("picker-dialog workdir-picker")}
            role="dialog"
            aria-label="选择工作目录"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>选择工作目录</div>
            <form
              className="dir-jump"
              onSubmit={(event) => {
                event.preventDefault()
                void loadDirs(pathDraft, "picker")
              }}
            >
              <input
                value={pathDraft}
                aria-label="文件夹路径"
                onChange={(event) => setPathDraft(event.target.value)}
              />
              <button type="submit">前往</button>
            </form>
            {pickerError ? <div className="picker-error">{pickerError}</div> : null}
            <ul className="dir-list picker-list" aria-label="可选目录">
              {pickerBrowse?.parent ? (
                <li className="is-up">
                  <button type="button" onClick={() => pickerBrowse.parent && void loadDirs(pickerBrowse.parent, "picker")}>
                    ..
                  </button>
                </li>
              ) : null}
              {pickerBrowse
                ? pickerBrowse.dirs.map((dir) => (
                    <li key={dir.path} className="is-dir">
                      <button type="button" onClick={() => void loadDirs(dir.path, "picker")}>
                        {dir.name}
                      </button>
                    </li>
                  ))
                : null}
              {pickerBrowse && pickerBrowse.dirs.length === 0 ? <li className="is-empty">没有子文件夹</li> : null}
              {!pickerBrowse ? <li className="is-empty">{pickerError ? "没有可显示的文件夹" : "正在读取"}</li> : null}
            </ul>
            <div className="dir-actions">
              <button type="button" onClick={() => setPickerOpen(false)}>
                取消
              </button>
              <button
                type="button"
                disabled={pickerBrowse === null}
                onClick={() => {
                  if (pickerBrowse === null) return
                  void chooseDirectory(pickerBrowse.path)
                }}
              >
                使用此目录
              </button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
      {entryMenu ? (
        <div
          ref={entryMenuRef}
          className="session-menu"
          role="menu"
          style={{ left: entryMenu.x, top: entryMenu.y }}
        >
          {entryMenuLabels(entryMenu.kind).map((label) => (
            <button key={label} type="button" role="menuitem" onClick={() => chooseEntryAction(label, entryMenu)}>
              {label}
            </button>
          ))}
        </div>
      ) : null}
      {preview ? (
        <div className="props-backdrop" onClick={() => setPreview(null)}>
          <div
            {...dialogFrame("picker-dialog file-preview")}
            role="dialog"
            aria-label="查看文件"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>{preview.name}</div>
            {preview.kind === "text" ? (
              <pre className="preview-text">
                {highlightCode(preview.text, preview.name).map((token, index) =>
                  token.kind === "plain" ? (
                    token.text
                  ) : (
                    <span key={index} className={`tok-${token.kind}`}>
                      {token.text}
                    </span>
                  ),
                )}
              </pre>
            ) : null}
            {preview.kind === "image" ? (
              <img
                className="preview-image"
                alt={preview.name}
                src={fileBytesUrl(preview.path, true)}
              />
            ) : null}
            {preview.kind === "too_large" ? <p className="picker-error">这个文件超过 2MB，不能预览</p> : null}
            {preview.kind === "unsupported" ? <p className="picker-error">这个文件不能预览</p> : null}
            <div className="dir-actions">
              <button type="button" onClick={() => setPreview(null)}>
                取消
              </button>
              <button type="button" onClick={() => downloadEntry(preview.path)}>
                下载
              </button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
      {renameTarget ? (
        <div className="props-backdrop" onClick={() => setRenameTarget(null)}>
          <form
            {...dialogFrame("picker-dialog")}
            aria-label="重命名"
            onClick={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault()
              void submitRename()
            }}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>重命名</div>
            <input
              className="rename-input"
              aria-label="新名称"
              value={renameTarget.draft}
              onChange={(event) =>
                setRenameTarget((current) => (current ? { ...current, draft: event.target.value } : current))
              }
            />
            <div className="dir-actions">
              <button type="button" onClick={() => setRenameTarget(null)}>
                取消
              </button>
              <button type="submit">确定</button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </form>
        </div>
      ) : null}
      {deleteTarget ? (
        <div className="props-backdrop" onClick={() => setDeleteTarget(null)}>
          <div
            {...dialogFrame("picker-dialog")}
            role="dialog"
            aria-label="删除"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>删除 {deleteTarget.name}？</div>
            <div className="dir-actions">
              <button type="button" onClick={() => setDeleteTarget(null)}>
                取消
              </button>
              <button type="button" onClick={() => void confirmDelete()}>
                删除
              </button>
            </div>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
    </>
  )
}

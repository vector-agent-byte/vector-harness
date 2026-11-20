import type { useAgentSession } from "./useAgentSession.ts"
import type { useAgentLayout } from "./useAgentLayout.ts"

export function AgentSessionDialogs({ session, layout }: { session: ReturnType<typeof useAgentSession>; layout: ReturnType<typeof useAgentLayout> }) {
  const { sessionMenu, setSessionMenu, menuRef, runningId, deleteSession, setPropsId, propsSession, propsTiming } = session
  const { dialogFrame, beginDialogDrag, beginDialogResize } = layout

  return (
    <>
      {sessionMenu ? (
        <div
          ref={menuRef}
          className="session-menu"
          role="menu"
          style={{ left: sessionMenu.x, top: sessionMenu.y }}
        >
          <button
            type="button"
            role="menuitem"
            disabled={sessionMenu.id === runningId}
            onClick={() => void deleteSession(sessionMenu.id)}
          >
            删除
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setPropsId(sessionMenu.id)
              setSessionMenu(null)
            }}
          >
            查看属性
          </button>
        </div>
      ) : null}
      {propsSession ? (
        <div
          className="props-backdrop"
          onClick={() => setPropsId(null)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setPropsId(null)
          }}
        >
          <div
            {...dialogFrame("props-card")}
            role="dialog"
            aria-label="会话属性"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="props-heading" onPointerDown={beginDialogDrag}>属性</div>
            <dl>
              <dt>标题</dt>
              <dd>{propsSession.title}</dd>
              <dt>技能</dt>
              <dd>{propsSession.skills === null ? "全部技能" : propsSession.skills.join("、") || "不使用技能"}</dd>
              <dt>触发</dt>
              <dd>{propsTiming?.trigger}</dd>
              <dt>耗时</dt>
              <dd>{propsTiming?.duration}</dd>
            </dl>
            <button type="button" className="props-close" onClick={() => setPropsId(null)}>
              关闭
            </button>
            <div className="dialog-resize" onPointerDown={beginDialogResize} />
          </div>
        </div>
      ) : null}
    </>
  )
}

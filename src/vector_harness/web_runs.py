"""同一时间只跑一轮。

锁、停止信号和正在跑的进程表都放在这里。HTTP 处理器只问「能不能开始」，
不再自己记这些状态。

这一轮的事件经 ``on_event`` 立刻写出，所以客户端能看见增量；停止请求
在另一条线程上调用 ``stop``，取消 asyncio 任务并结束子进程。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vector_harness.bootstrap import build_agent
from vector_harness.core.session import Session
from vector_harness.tools.shell import Shell, signal_kill
from vector_harness.types import Message, ProviderEvent, Role
from vector_harness.web_sessions import begin_run, finish_run, session_skill

_logger = logging.getLogger("vector_harness.web")


@dataclass(frozen=True, kw_only=True)
class RunSettings:
    """启动服务时定下来、每一轮都要用到的装配参数。

    ``workspace`` 同时是会话目录的根，页面不能改。工具的工作目录由
    ``workdir`` 提供，可以随页面切换。
    """

    workspace: Path
    workdir: Callable[[], Path]
    skills_dir: Path | None = None
    memory_path: Path | None = None
    compact: bool = False
    plan: bool = False
    reflect: bool = False
    subagents: bool = False
    max_steps: int = 25


class RunManager:
    """一份服务同时只跑一轮。``running_id`` 是那一轮的会话 id，没有时是 None。"""

    def __init__(
        self,
        settings: RunSettings,
        provider: object,
        emit: Callable[[ProviderEvent], None],
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.emit = emit
        self.running_id: str | None = None
        # 盖住「检查正忙」到这一轮结束。拿不到锁就是已经有一轮。
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._processes: list = []
        self._process_lock = threading.Lock()
        self._run_loop: asyncio.AbstractEventLoop | None = None
        self._run_task: asyncio.Task | None = None

    def acquire(self) -> bool:
        """占住这一轮。已经有一轮在跑时返回 False，调用方回 409。"""
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        self._lock.release()

    def run(
        self,
        session_id: str,
        session_path: Path,
        text: str,
        *,
        plan: bool,
        reflect: bool,
        subagents: bool = False,
    ) -> tuple[str, str]:
        """跑一轮并把结果写进会话。调用方先 ``acquire``，结束时 ``release``。

        返回 ``(status, text)``。停止时 status 是 ``"stopped"``，text 留空。
        """
        workspace = self.settings.workspace
        self._cancel.clear()
        self.running_id = session_id
        begin_run(workspace, session_id)
        _logger.info("run start  session=%s text=%.120r", session_id, text)
        fragment: list[str] = []

        def on_event(event: ProviderEvent) -> None:
            if event.kind == "tool_call_end":
                fragment.clear()
            elif event.kind == "text_delta" and event.origin != "child" and event.text:
                fragment.append(event.text)
            self.emit(event)

        try:
            agent = self._build(session=Session(session_path), plan=plan, reflect=reflect, subagents=subagents)
            for tool in agent.loop.tools:
                if isinstance(tool, Shell):
                    tool.cancel = self._cancel
                    tool.processes = self._processes
                    tool.process_lock = self._process_lock
            agent.loop.on_event = on_event
            result = asyncio.run(self._drive(agent.run(text), fragment, session_path))
            status = "stopped" if result is None else result.status
            content = "" if result is None else result.text
            if status == "error":
                _logger.error("run_result error: %s", content or "(no detail)")
            else:
                _logger.info("run_result status=%s", status)
            return status, content
        finally:
            self.running_id = None
            finish_run(workspace, session_id)
            _logger.info("run finish session=%s", session_id)

    def stop(self, session_id: str) -> bool:
        """停下正在跑的那一轮。不是这一份会话时返回 False。"""
        if self.running_id != session_id:
            return False
        self._cancel.set()
        with self._process_lock:
            procs = list(self._processes)
        for proc in procs:
            signal_kill(proc)
        loop = self._run_loop
        task = self._run_task
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)
        return True

    def _build(self, *, session: Session, plan: bool, reflect: bool, subagents: bool = False):
        """按这一份会话选中的技能装配这一轮。"""
        settings = self.settings
        chosen = session_skill(settings.workspace, session.path.stem)
        return build_agent(
            provider=self.provider,
            workspace=settings.workdir(),
            session=session,
            skills_dir=settings.skills_dir if chosen else None,
            skill_name=chosen,
            memory_path=settings.memory_path,
            compact=settings.compact,
            plan=plan,
            reflect=reflect,
            subagents=settings.subagents or subagents,
            max_steps=settings.max_steps,
        )

    async def _drive(self, turn, fragment: list[str], session_path: Path):
        """在事件循环里跑这一轮。被取消时补上已流出的正文。"""
        self._run_loop = asyncio.get_running_loop()
        self._run_task = asyncio.current_task()
        try:
            if self._cancel.is_set():
                self._keep_partial(session_path, "".join(fragment))
                return None
            return await turn
        except asyncio.CancelledError:
            self._keep_partial(session_path, "".join(fragment))
            return None
        finally:
            self._run_task = None
            self._run_loop = None

    @staticmethod
    def _keep_partial(session_path: Path, text: str) -> None:
        """停止时把还没写入会话的正文补上。已经落盘的不再写一遍。"""
        if text == "":
            return
        session = Session(session_path)
        messages = session.load()
        if messages and messages[-1].role == Role.ASSISTANT and messages[-1].content == text:
            return
        session.append(Message(role=Role.ASSISTANT, content=text))

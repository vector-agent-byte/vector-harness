"""把一轮对话存成 JSONL。

每行一个消息，键固定为 ``role``、``content``、``tool_calls``、``tool_call_id``、
``is_error``。写下时再补 ``created_at``。``path is None`` 的会话只留在内存里，给子循环用，不碰磁盘。

文件会话在内存里留一份解析结果，用 ``(mtime_ns, size)`` 判断还对不对得上。
工具循环每一步都要读历史，缓存把「每步读一遍整个文件」降到「一轮读一次」。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from vector_harness.agent.core.codec import message_to_dict
from vector_harness.agent.core.session_io import atomic_write_bytes, repair_partial_tail, scan_session
from vector_harness.types import Message


_logger = logging.getLogger(__name__)


@dataclass
class Session:
    """一份会话。有路径就读写那个 JSONL 文件，没有路径就只留在内存。"""

    path: Path | None
    _messages: list[Message] = field(default_factory=list, init=False, repr=False)
    _stamp: tuple[int, int] | None = field(default=None, init=False, repr=False)
    _derived_state: dict[str, dict] = field(default_factory=dict, init=False, repr=False)
    _partial_tail: bool = field(default=False, init=False, repr=False)
    runtime_context: str = field(default="", init=False, repr=False)

    @classmethod
    def in_memory(cls) -> Session:
        """子循环用的会话。写入不会创建文件。"""
        return cls(path=None)

    def load(self) -> list[Message]:
        """读出全部消息。文件没变就用上次解析的结果。

        返回副本。调用方改这个列表，不会直接改掉会话里的原列表。
        """
        if self.path is None:
            return list(self._messages)
        if not self._fresh():
            self._reload()
        return list(self._messages)

    def append(self, message: Message) -> None:
        """追加一条。文件在第一次写入时才创建，所以只打开会话不会留下空文件。

        还没有写下时间的消息，在这里记上当前时间。用户发出的文字和模型返回的文字都走这里。
        """
        if message.created_at is None:
            message.created_at = time.time()
        if self.path is None:
            self._messages.append(message)
            return
        if self._partial_tail or not self._fresh():
            self.prepare_for_run()
        current = self._fresh()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(message_to_dict(message), ensure_ascii=False)
        with self.path.open("ab+") as stream:
            if stream.tell():
                stream.seek(-1, 2)
                if stream.read(1) not in (b"\n", b"\r"):
                    stream.write(b"\n")
            stream.write((line + "\n").encode("utf-8"))
            stream.flush()
        if current:
            self._messages.append(message)
            self._stamp = self._key()
        else:
            # 缓存本来就不新鲜，下一次 load 重读，不在这里拼接。
            self._stamp = None

    def replace_all(self, messages: list[Message]) -> None:
        """显式重写会话；上下文变换不调用此方法。"""
        if self.path is None:
            self._messages = list(messages)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(message_to_dict(m), ensure_ascii=False) for m in messages]
        content = "\n".join(lines)
        # 最后一条也以换行结束，和 append 的行格式一致。这是整份覆盖。
        if lines:
            content += "\n"
        atomic_write_bytes(self.path, content.encode("utf-8"))
        self._messages = list(messages)
        self._partial_tail = False
        self._stamp = self._key()

    def prepare_for_run(self) -> None:
        if self.path is None:
            return
        backup = repair_partial_tail(self.path)
        if backup is not None:
            _logger.warning("Recovered incomplete session tail; preserved backup %s", backup.name)
        self._reload()

    def _key(self) -> tuple[int, int] | None:
        """文件的版本标记。读不到时是 None。"""
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _fresh(self) -> bool:
        """缓存和磁盘对得上。"""
        return self._stamp is not None and self._stamp == self._key()

    def _reload(self) -> None:
        scan = scan_session(self.path)
        self._messages = scan.messages
        self._partial_tail = scan.issue == "partial_tail"
        if self._partial_tail:
            _logger.warning("Session has an incomplete tail; read-only access leaves it unchanged")
        self._stamp = self._key()

"""把一轮对话存成 JSONL。

每行一个消息，键固定为 ``role``、``content``、``tool_calls``、``tool_call_id``、
``is_error``。写下时再补 ``created_at``。``path is None`` 的会话只留在内存里，给子循环用，不碰磁盘。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from vector_harness.core.codec import message_from_dict, message_to_dict
from vector_harness.types import Message


@dataclass
class Session:
    """一份会话。有路径就读写那个 JSONL 文件，没有路径就只留在内存。"""

    path: Path | None

    @classmethod
    def in_memory(cls) -> Session:
        """子循环用的会话。写入不会创建文件。"""
        return cls(path=None)

    def __post_init__(self) -> None:
        """内存会话的消息放在这里。有文件路径时以文件为准。"""
        self._messages: list[Message] = []

    def load(self) -> list[Message]:
        """读出全部消息。文件还不存在或是空的，返回空列表。"""
        if self.path is None:
            # 返回副本。调用方改这个列表，不会直接改掉会话里的原列表。
            return list(self._messages)
        if not self.path.is_file():
            return []
        text = self.path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        messages: list[Message] = []
        for line in text.splitlines():
            # 空行不是消息。文件末尾多出来的换行落在这里。
            if not line.strip():
                continue
            messages.append(message_from_dict(json.loads(line)))
        return messages

    def append(self, message: Message) -> None:
        """追加一条。文件在第一次写入时才创建，所以只打开会话不会留下空文件。

        还没有写下时间的消息，在这里记上当前时间。用户发出的文字和模型返回的文字都走这里。
        """
        if message.created_at is None:
            message.created_at = time.time()
        if self.path is None:
            self._messages.append(message)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 中文原样写入。每条独占一行，中断时最多损坏刚写下的这一行。
        line = json.dumps(message_to_dict(message), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def replace_all(self, messages: list[Message]) -> None:
        """整份重写。压缩把前缀折成摘要之后用它替换原文。"""
        if self.path is None:
            self._messages = list(messages)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(message_to_dict(m), ensure_ascii=False) for m in messages]
        content = "\n".join(lines)
        # 最后一条也以换行结束，和 append 的行格式一致。这是整份覆盖。
        if lines:
            content += "\n"
        self.path.write_text(content, encoding="utf-8")

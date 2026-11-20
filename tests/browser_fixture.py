"""Standalone real HTTP fixture for web/backend.browser.mjs; not a pytest test."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from vector_harness.types import ProviderEvent
from vector_harness.web.server import WebServer, WebSettings


def announce(event: str, **values: object) -> None:
    print(json.dumps({"event": event, **values}, ensure_ascii=True), flush=True)


class BrowserProvider:
    """Exercise real streaming and projection without tools or external services."""

    async def stream(self, *, system, messages, tools):
        prompt = next(message.content for message in reversed(messages) if message.role == "user")
        if "执行自进化建模任务" in prompt and "modeling-report" in prompt:
            kind = "autoresearch"
            experiments = [
                {"id": 0, "title": "Browser baseline", "score": 0.71, "algorithm": "Scripted baseline"},
                {"id": 1, "title": "Browser best", "score": 0.89, "algorithm": "Scripted candidate"},
            ]
            for experiment in experiments:
                experiment.update(plan="Deterministic browser fixture", result="Synthetic smoke score; no training performed",
                                  code="print('browser fixture')", duration="0s")
            text = "Browser modeling report\n\n```modeling-report\n" + json.dumps({"experiments": experiments}) + "\n```\n\nSynthetic browser smoke completed."
        elif "请对以下主题进行深度研究" in prompt:
            kind = "deepresearch"
            text = "# Browser research complete\n\nDeterministic integration report. No external searches or verified sources are claimed."
        elif prompt == "Browser agent smoke":
            kind = "agent"
            text = "Browser agent complete"
        else:
            raise AssertionError(f"Unexpected browser fixture prompt: {prompt[:160]!r}")
        announce("provider", kind=kind)
        for offset in range(0, len(text), 48):
            yield ProviderEvent(kind="text_delta", text=text[offset:offset + 48])
            await asyncio.sleep(0.01)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parents[1] / "web" / "dist")
    args = parser.parse_args()
    if not (args.dist / "index.html").is_file():
        parser.error("Frontend build missing; run npm run build in web first")
    with TemporaryDirectory(prefix="vector-browser-workspace-") as directory:
        workspace = Path(directory)
        (workspace / "data").mkdir()
        (workspace / "data" / "train.csv").write_text("feature,target\n0,0\n1,1\n", encoding="utf-8")
        server = WebServer(WebSettings(workspace=workspace, dist_dir=args.dist.resolve()), BrowserProvider())
        try:
            server.start(port=0)
            announce("ready", port=server.port, workspace=str(workspace))
            for line in sys.stdin:
                if line.strip() == "shutdown":
                    break
        finally:
            server.shutdown()
    announce("stopped", workspace_removed=not workspace.exists())


if __name__ == "__main__":
    main()

"""本机网页入口。

只绑定 ``127.0.0.1``。没有 ``--host``。默认端口 8787。
"""

from __future__ import annotations

import argparse
import socket
import sys
import webbrowser
from collections.abc import Callable, Mapping
from pathlib import Path

from vector_harness.bootstrap import load_provider, memory_path as _memory_path
from vector_harness.types import ProviderError
from vector_harness.web_server import WebServer, WebSettings


def _parser() -> argparse.ArgumentParser:
    """与终端共用工作目录和模式开关。密钥没有对应参数。"""
    parser = argparse.ArgumentParser(
        prog="vector-harness-web",
        description=(
            "Serve an agent workspace in the browser on 127.0.0.1. "
            "Connection settings can live in ~/.vector-harness/config.toml "
            "as api_key, base_url, and model."
        ),
    )
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Append long-term memory at {workspace}/.vector/MEMORY.md.",
    )
    parser.add_argument(
        "--memory-path",
        default=None,
        help="Memory file to use instead of the workspace default.",
    )
    parser.add_argument(
        "--skills",
        default=None,
        help="Skill directory. Defaults to ./skills when that directory exists.",
    )
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--reflect", action="store_true")
    parser.add_argument("--subagents", action="store_true")
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--open", action="store_true")
    return parser


def _port_busy(port: int) -> OSError | None:
    """端口已被占用时返回绑定错误。

    ``HTTPServer`` 打开了 ``SO_REUSEADDR``。Windows 上因此仍能再绑一次，
    所以这里用没有该选项的套接字先确认端口是空的。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError as exc:
        return exc
    finally:
        probe.close()
    return None


def _browse(port: int, opener: Callable[[str], None] | None) -> None:
    """打开本机页面。浏览器打不开时仍然继续服务。"""
    browse = webbrowser.open if opener is None else opener
    try:
        browse(f"http://127.0.0.1:{port}/")
    except Exception:
        pass


def _serve(server: WebServer, port: int) -> int:
    try:
        server.serve_forever("127.0.0.1", port)
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    provider=None,
    config_file: Path | None = None,
    opener: Callable[[str], None] | None = None,
    server_factory: Callable[[WebSettings, object], WebServer] = WebServer,
) -> int:
    """浏览器入口。成功返回 0。缺配置、目录无效或端口已被占用时返回 1。"""
    args = _parser().parse_args(argv)
    workspace = Path(args.workspace)
    if not workspace.is_dir():
        print(args.workspace, file=sys.stderr)
        return 1
    skills_dir: Path | None = None
    if args.skills is not None:
        skills_dir = Path(args.skills)
        if not skills_dir.is_dir():
            print("skills directory not found", file=sys.stderr)
            return 1
    else:
        candidate = Path.cwd() / "skills"
        if candidate.is_dir():
            skills_dir = candidate
    if provider is None:
        try:
            provider = load_provider(
                environ=environ,
                config_file=config_file,
                model=args.model,
                base_url=args.base_url,
            )
        except ProviderError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    settings = WebSettings(
        workspace=workspace,
        skills_dir=skills_dir,
        memory_path=_memory_path(args.memory, args.memory_path, workspace),
        compact=args.compact,
        plan=args.plan,
        reflect=args.reflect,
        subagents=args.subagents,
        max_steps=args.max_steps,
        dist_dir=Path.cwd() / "web" / "dist",
    )
    server = server_factory(settings, provider)
    if isinstance(server, WebServer):
        busy = _port_busy(args.port)
        if busy is not None:
            print(str(busy), file=sys.stderr)
            return 1
        if args.open:
            try:
                bound = server.listen("127.0.0.1", args.port)
            except OSError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _browse(bound, opener)
            return _serve(server, bound)
    if args.open:
        _browse(args.port, opener)
    return _serve(server, args.port)


if __name__ == "__main__":
    raise SystemExit(main())

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
MODULES = (
    "assembly",
    "core.agent", "core.codec", "core.config", "core.context", "core.dispatch",
    "core.loop", "core.openai_events", "core.provider", "core.session",
    "core.session_io", "core.session_state", "core.turn",
    "patterns.compact", "patterns.compact_state", "patterns.memory", "patterns.plan",
    "patterns.reflect", "patterns.skills", "patterns.subagent", "patterns.task_state",
    "tools.calculator", "tools.edit", "tools.fetch", "tools.history", "tools.read", "tools.shell",
)


def _run_clean(code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=SRC_ROOT.parent,
        env=dict(os.environ, PYTHONPATH=str(SRC_ROOT)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("canonical_first", [False, True])
def test_legacy_modules_alias_canonical_implementations(canonical_first):
    _run_clean(f"""
        import importlib
        import inspect
        import sys
        from pathlib import Path

        for suffix in {MODULES!r}:
            old_name = "vector_harness." + suffix
            new_name = "vector_harness.agent." + suffix
            names = (new_name, old_name) if {canonical_first!r} else (old_name, new_name)
            first = importlib.import_module(names[0])
            second = importlib.import_module(names[1])
            assert first is second, suffix
            assert sys.modules[old_name] is sys.modules[new_name], suffix
            assert first.__name__ == new_name, suffix
            assert "agent" in Path(first.__file__).parts, suffix
            for value in vars(first).values():
                if inspect.isclass(value) or inspect.isfunction(value):
                    assert value.__module__ != old_name, (suffix, value)
    """)


def test_legacy_module_eviction_preserves_class_identity():
    _run_clean(f"""
        import importlib
        import sys
        from vector_harness import VectorHarness
        from vector_harness.patterns.compact import Compaction

        originals = {{suffix: importlib.import_module("vector_harness." + suffix)
                     for suffix in {MODULES!r}}}
        for name in list(sys.modules):
            if any(name == "vector_harness." + prefix or name.startswith("vector_harness." + prefix + ".")
                   for prefix in ("core", "patterns", "tools", "assembly")):
                del sys.modules[name]

        for suffix, original in originals.items():
            assert importlib.import_module("vector_harness." + suffix) is original, suffix

        from vector_harness import attach
        agent = VectorHarness(name="agent", llm=object(), system_prompt="system")
        attach(agent, compact=True)
        assert isinstance(agent.loop.context_transforms[0], Compaction)
    """)


def test_legacy_monkeypatches_reach_canonical_call_sites():
    _run_clean("""
        from unittest.mock import patch
        from vector_harness.agent.core.agent import VectorHarness
        from vector_harness.agent.core.loop import Loop
        from vector_harness.agent.assembly import attach, apply_patterns

        with patch("vector_harness.core.agent.Loop", wraps=Loop) as create_loop:
            agent = VectorHarness(name="agent", llm=object(), system_prompt="system")
            create_loop.assert_called_once()
        with patch("vector_harness.assembly.apply_patterns", wraps=apply_patterns) as assemble:
            attach(agent, plan=True)
            assemble.assert_called_once()
        from vector_harness.patterns.plan import TodoPlan
        assert isinstance(agent.runner, TodoPlan)
    """)


def test_public_exports_and_bootstrap_keep_canonical_identity():
    _run_clean("""
        import vector_harness
        from vector_harness import bootstrap
        from vector_harness.agent import assembly
        from vector_harness.agent.core.agent import VectorHarness
        from vector_harness.agent.core.loop import Loop
        from vector_harness.agent.core.provider import OpenAICompatibleProvider
        from vector_harness.agent.core.session import Session
        from vector_harness.agent.tools.calculator import Calculator
        from vector_harness.agent.tools.edit import EditFile
        from vector_harness.agent.tools.read import ReadFile
        from vector_harness.agent.tools.shell import Shell

        expected = [
            "Message", "ToolCall", "RunResult", "ProviderEvent", "ProviderError", "Role",
            "RunStatus", "EventKind", "Model", "Session", "Loop", "VectorHarness",
            "OpenAICompatibleProvider", "ReadFile", "EditFile", "Shell", "Calculator", "runner_chain",
        ]
        assert vector_harness.__all__ == expected
        for name in ("VectorHarness", "Loop", "OpenAICompatibleProvider", "Session",
                     "Calculator", "EditFile", "ReadFile", "Shell"):
            assert getattr(vector_harness, name) is globals()[name], name
        assert vector_harness.attach is assembly.attach
        assert vector_harness.runner_chain is assembly.runner_chain
        assert bootstrap.apply_patterns is assembly.apply_patterns
        assert bootstrap.Loop is Loop
        assert bootstrap.Shell is Shell
    """)

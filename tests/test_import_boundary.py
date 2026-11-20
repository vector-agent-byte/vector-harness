import ast
import os
from importlib.util import resolve_name
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "vector_harness"
AGENT_ROOT = SRC_ROOT / "agent"
DOMAIN_IMPORTS = (
    "vector_harness.web",
    "vector_harness.deepresearch",
    "vector_harness.autoresearch",
)
CORE_FORBIDDEN = DOMAIN_IMPORTS + (
    "vector_harness.patterns",
    "vector_harness.agent.patterns",
    "vector_harness.agent.application",
    "vector_harness.cli",
)


def _module_names(node: ast.AST, package: str):
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level:
            module = resolve_name("." * node.level + module, package)
        yield module
        for alias in node.names:
            yield f"{module}.{alias.name}"


def imports_of(paths: list[Path], forbidden: tuple[str, ...]) -> list[str]:
    offenders: set[str] = set()
    for path in paths:
        package = ".".join(path.parent.relative_to(SRC_ROOT.parent).parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for name in _module_names(node, package):
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    offenders.add(f"{path.relative_to(SRC_ROOT.parent)}: {name}")
    return sorted(offenders)


def _run_clean(code: str) -> None:
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT.parent))
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=SRC_ROOT.parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("construct", [False, True])
def test_plain_harness_does_not_load_patterns_or_application(construct):
    _run_clean(f"""
        import sys
        import vector_harness

        if {construct!r}:
            vector_harness.VectorHarness(name="agent", llm=object(), system_prompt="system")

        forbidden = {CORE_FORBIDDEN + ('vector_harness.assembly', 'vector_harness.agent.assembly')!r}
        loaded = [name for name in sys.modules if any(
            name == prefix or name.startswith(prefix + ".") for prefix in forbidden
        )]
        assert loaded == [], loaded
        assert "vector_harness.agent.core.agent" in sys.modules
    """)


def test_attach_import_is_lazy():
    _run_clean("""
        import sys
        import vector_harness

        assert "vector_harness.agent.assembly" not in sys.modules
        assert "vector_harness.agent.patterns" not in sys.modules
        from vector_harness import attach
        from vector_harness.agent.assembly import attach as canonical_attach

        assert attach is canonical_attach
        assert "vector_harness.agent.patterns" in sys.modules
        assert "vector_harness.agent.application" not in sys.modules
        assert "vector_harness.web" not in sys.modules
        assert "vector_harness.cli" not in sys.modules
    """)


def test_core_tools_and_public_root_do_not_import_upper_layers():
    paths = [SRC_ROOT / "__init__.py"]
    for root in (SRC_ROOT, AGENT_ROOT):
        for directory in ("core", "tools"):
            paths.extend(sorted((root / directory).rglob("*.py")))
    assert imports_of(paths, CORE_FORBIDDEN) == []


def test_agent_does_not_import_transport_or_research_domains():
    assert imports_of(sorted(AGENT_ROOT.rglob("*.py")), DOMAIN_IMPORTS) == []


def test_moved_implementation_uses_canonical_imports():
    paths = [AGENT_ROOT / "assembly.py"]
    for directory in ("core", "patterns", "tools"):
        paths.extend(sorted((AGENT_ROOT / directory).rglob("*.py")))
    assert imports_of(paths, (
        "vector_harness.core",
        "vector_harness.patterns",
        "vector_harness.tools",
        "vector_harness.assembly",
    )) == []

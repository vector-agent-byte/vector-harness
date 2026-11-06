import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "vector_harness"

src_roots = [
    SRC_ROOT / "__init__.py",
    *sorted((SRC_ROOT / "core").glob("*.py")),
    *sorted((SRC_ROOT / "tools").glob("*.py")),
]

FORBIDDEN = ("vector_harness.patterns", "vector_harness.cli")


def _module_names(node: ast.AST):
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    elif isinstance(node, ast.ImportFrom) and node.module:
        yield node.module


def imports_of(paths: list[Path]) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name in _module_names(node):
                    if name and any(
                        name == forbidden or name.startswith(forbidden + ".")
                        for forbidden in FORBIDDEN
                    ):
                        offenders.append(f"{path.relative_to(SRC_ROOT.parent.parent)}: {name}")
    return sorted(offenders)


def test_package_root_does_not_import_patterns_or_cli():
    import sys

    import vector_harness

    assert "vector_harness.patterns" not in sys.modules
    assert "vector_harness.cli" not in sys.modules
    offenders = imports_of(src_roots)
    assert offenders == []

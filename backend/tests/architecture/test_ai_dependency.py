import ast
from pathlib import Path

import brokerage_ai

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_brokerage_ai_is_available_in_backend_environment() -> None:
    assert "create_ai_runtime" in brokerage_ai.__all__
    assert "LlmProvider" in brokerage_ai.__all__


def test_backend_source_does_not_import_provider_sdk_or_workflow_framework() -> None:
    forbidden = {"langgraph", "openai"}
    violations = {
        str(path.relative_to(BACKEND_ROOT)): sorted(imported_roots(path) & forbidden)
        for path in (BACKEND_ROOT / "src").rglob("*.py")
        if imported_roots(path) & forbidden
    }

    assert violations == {}

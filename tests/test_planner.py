from __future__ import annotations

from swarm_mcp.planner import (
    classify_task_category,
    decompose_task,
    normalize_task,
    task_similarity,
)


def test_decompose_security_task() -> None:
    subtasks = decompose_task("audit the codebase for security vulnerabilities")
    names = {task["name"] for task in subtasks}
    assert {"auth-audit", "config-audit", "dependency-audit"}.issubset(names)


def test_decompose_fallback_task() -> None:
    subtasks = decompose_task("do the thing")
    assert subtasks == [{"name": "primary", "task": "do the thing"}]


def test_normalize_task_collapses_case_and_whitespace() -> None:
    assert normalize_task("  Analyze   Auth  Module ") == "analyze auth module"


def test_classify_task_category_detects_audit_and_debug() -> None:
    assert classify_task_category("Audit the auth module for vulnerabilities") == "audit"
    assert classify_task_category("Fix the failing login bug") == "debug"


def test_task_similarity_detects_rephrased_duplicates() -> None:
    similarity = task_similarity(
        "analyze auth module for vulnerabilities",
        "analyze the auth module vulnerabilities",
    )
    assert similarity >= 0.8

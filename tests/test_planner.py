from __future__ import annotations

from swarm_mcp.planner import (
    SemanticDeduplicator,
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


def test_semantic_deduplicator_finds_similar_tasks() -> None:
    dedup = SemanticDeduplicator(similarity_threshold=0.75)
    existing = [
        "refactor payment service code",
        "implement user profile page",
        "audit authentication module",
    ]
    similarity, match = dedup.find_best_match("cleanup payment service implementation", existing)
    assert 0.3 <= similarity < 0.75
    assert match == "refactor payment service code"


def test_semantic_deduplicator_returns_low_for_dissimilar() -> None:
    dedup = SemanticDeduplicator(similarity_threshold=0.75)
    existing = ["refactor payment service", "implement login page"]
    similarity, match = dedup.find_best_match("deploy to production server", existing)
    assert similarity < 0.4
    assert match is not None


def test_semantic_deduplicator_exact_match() -> None:
    dedup = SemanticDeduplicator(similarity_threshold=0.75)
    existing = ["fix the login bug", "update dependencies"]
    similarity, match = dedup.find_best_match("fix the login bug", existing)
    assert similarity > 0.99
    assert match == "fix the login bug"


def test_semantic_deduplicator_empty_corpus() -> None:
    dedup = SemanticDeduplicator(similarity_threshold=0.75)
    similarity, match = dedup.find_best_match("some task", [])
    assert similarity == 0.0
    assert match is None


def test_semantic_deduplicator_similarity_method() -> None:
    dedup = SemanticDeduplicator(similarity_threshold=0.75)
    existing = [
        "refactor payment service code",
        "implement user profile page",
    ]
    dedup.update_corpus(existing + ["cleanup payment service implementation"])
    sim = dedup.similarity("cleanup payment service implementation", existing[0])
    assert 0.3 <= sim < 0.75

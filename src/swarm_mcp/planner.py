"""Lightweight task decomposition helpers for semi-autonomous workflows."""

from __future__ import annotations

from typing import Any


def normalize_task(task: str) -> str:
    return " ".join(task.lower().split())


def classify_task_category(task: str) -> str:
    lowered = normalize_task(task)
    if any(token in lowered for token in ["security", "vulnerab", "audit"]):
        return "audit"
    if any(token in lowered for token in ["refactor", "cleanup", "simplify"]):
        return "refactor"
    if any(token in lowered for token in ["implement", "build", "create", "add feature"]):
        return "implement"
    if any(token in lowered for token in ["debug", "fix", "bug", "error"]):
        return "debug"
    if any(token in lowered for token in ["test", "verify", "validate"]):
        return "test"
    return "general"


def task_similarity(left: str, right: str) -> float:
    stopwords = {"the", "a", "an", "for", "to", "of"}
    left_tokens = {token for token in normalize_task(left).split() if token not in stopwords}
    right_tokens = {token for token in normalize_task(right).split() if token not in stopwords}
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union


def decompose_task(task: str) -> list[dict[str, Any]]:
    lowered = task.lower()
    if "security" in lowered or "vulnerab" in lowered or "audit" in lowered:
        return [
            {
                "name": "auth-audit",
                "task": (
                    "Audit authentication and authorization paths. "
                    f"Base task: {task}"
                ),
            },
            {
                "name": "config-audit",
                "task": (
                    "Audit configuration, secrets, and environment handling. "
                    f"Base task: {task}"
                ),
            },
            {
                "name": "dependency-audit",
                "task": (
                    "Audit dependencies and external integrations. "
                    f"Base task: {task}"
                ),
            },
        ]
    if "refactor" in lowered:
        return [
            {
                "name": "structure-review",
                "task": (
                    "Review module structure and identify refactor seams. "
                    f"Base task: {task}"
                ),
            },
            {
                "name": "change-plan",
                "task": f"Draft concrete refactor steps with risks. Base task: {task}",
            },
        ]
    if "implement" in lowered or "build" in lowered:
        return [
            {
                "name": "requirements-breakdown",
                "task": (
                    "Extract the smallest concrete implementation units. "
                    f"Base task: {task}"
                ),
            },
            {
                "name": "integration-notes",
                "task": (
                    "Identify integration and verification points. "
                    f"Base task: {task}"
                ),
            },
        ]
    return [{"name": "primary", "task": task}]

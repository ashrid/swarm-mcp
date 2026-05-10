"""Lightweight task decomposition helpers for semi-autonomous workflows."""

from __future__ import annotations

import math
from collections import Counter
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


def _tokenize(text: str) -> list[str]:
    stopwords = {"the", "a", "an", "for", "to", "of", "in", "on", "at", "by", "and", "or"}
    return [token for token in normalize_task(text).split() if token not in stopwords]


def _simple_stem(token: str) -> str:
    suffixes = ("ing", "ion", "ions", "ed", "er", "ers", "ies", "y", "s")
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    return token


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {token: count / total for token, count in counts.items()}


def _compute_idf(token: str, document_frequencies: dict[str, int], total_documents: int) -> float:
    doc_freq = document_frequencies.get(token, 0)
    return math.log((total_documents + 1) / (doc_freq + 1)) + 1


def _vectorize(
    text: str, document_frequencies: dict[str, int], total_documents: int
) -> dict[str, float]:
    tokens = [_simple_stem(token) for token in _tokenize(text)]
    tf = _compute_tf(tokens)
    return {
        token: tf[token] * _compute_idf(token, document_frequencies, total_documents)
        for token in tf
    }


def _cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    all_tokens = set(vec1.keys()) | set(vec2.keys())
    dot_product = sum(vec1.get(token, 0) * vec2.get(token, 0) for token in all_tokens)
    mag1 = math.sqrt(sum(v**2 for v in vec1.values()))
    mag2 = math.sqrt(sum(v**2 for v in vec2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product / (mag1 * mag2)


def _ngrams(text: str, n: int) -> set[str]:
    normalized = normalize_task(text)
    if len(normalized) < n:
        return set()
    return {normalized[i : i + n] for i in range(len(normalized) - n + 1)}


def _ngram_similarity(left: str, right: str, n: int = 3) -> float:
    left_ngrams = _ngrams(left, n)
    right_ngrams = _ngrams(right, n)
    if not left_ngrams and not right_ngrams:
        return 0.0
    if not left_ngrams or not right_ngrams:
        return 0.0
    intersection = len(left_ngrams & right_ngrams)
    union = len(left_ngrams | right_ngrams)
    return intersection / union


def _bigram_similarity(left: str, right: str) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens and not right_tokens:
        return 0.0
    left_bigrams = {f"{left_tokens[i]} {left_tokens[i + 1]}" for i in range(len(left_tokens) - 1)}
    right_bigrams = {
        f"{right_tokens[i]} {right_tokens[i + 1]}" for i in range(len(right_tokens) - 1)
    }
    if not left_bigrams and not right_bigrams:
        return 0.0
    if not left_bigrams or not right_bigrams:
        return 0.0
    intersection = len(left_bigrams & right_bigrams)
    union = len(left_bigrams | right_bigrams)
    return intersection / union


class SemanticDeduplicator:
    """TF-IDF based semantic deduplicator with corpus-aware similarity."""

    def __init__(self, similarity_threshold: float = 0.8):
        self.similarity_threshold = similarity_threshold
        self._document_frequencies: dict[str, int] = {}
        self._total_documents = 0

    def update_corpus(self, tasks: list[str]) -> None:
        self._document_frequencies = Counter()
        self._total_documents = len(tasks)
        for task in tasks:
            tokens = {_simple_stem(token) for token in _tokenize(task)}
            for token in tokens:
                self._document_frequencies[token] += 1

    def similarity(self, left: str, right: str) -> float:
        left_norm = normalize_task(left)
        right_norm = normalize_task(right)
        if not left_norm or not right_norm:
            return 0.0
        if left_norm == right_norm:
            return 1.0
        vec1 = _vectorize(left, self._document_frequencies, self._total_documents)
        vec2 = _vectorize(right, self._document_frequencies, self._total_documents)
        tfidf_sim = _cosine_similarity(vec1, vec2)
        bigram_sim = _bigram_similarity(left, right)
        char_sim = _ngram_similarity(left, right, n=3)
        category_bonus = (
            0.15 if classify_task_category(left) == classify_task_category(right) else 0.0
        )
        return min(1.0, 0.35 * tfidf_sim + 0.25 * bigram_sim + 0.25 * char_sim + category_bonus)

    def find_best_match(self, new_task: str, existing_tasks: list[str]) -> tuple[float, str | None]:
        if not existing_tasks:
            return 0.0, None
        self.update_corpus(existing_tasks + [new_task])
        best_similarity = 0.0
        best_match = existing_tasks[0]
        for task in existing_tasks:
            sim = self.similarity(new_task, task)
            if sim > best_similarity:
                best_similarity = sim
                best_match = task
        return best_similarity, best_match


def task_similarity(left: str, right: str) -> float:
    dedup = SemanticDeduplicator()
    dedup.update_corpus([left, right])
    return dedup.similarity(left, right)


def decompose_task(task: str) -> list[dict[str, Any]]:
    lowered = task.lower()
    if "security" in lowered or "vulnerab" in lowered or "audit" in lowered:
        return [
            {
                "name": "auth-audit",
                "task": ("Audit authentication and authorization paths. " f"Base task: {task}"),
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
                    "Audit dependencies and external integrations. " f"Base task: {task}"
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
                    "Identify integration and verification points. " f"Base task: {task}"
                ),
            },
        ]
    return [{"name": "primary", "task": task}]

"""Health and staleness helpers for worker monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .types import WorkerState


def parse_iso_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def latest_activity_iso(status_updated_at: str, progress_payload: dict[str, Any] | None) -> str:
    if progress_payload and isinstance(progress_payload.get("updated_at"), str):
        return str(progress_payload["updated_at"])
    return status_updated_at


def compute_staleness_transition(
    *,
    current_state: WorkerState,
    latest_activity_at: str,
    now: datetime,
    stale_after_seconds: int,
    stale_kill_after_seconds: int,
    has_result: bool,
) -> WorkerState | None:
    if has_result:
        return WorkerState.DONE if current_state != WorkerState.DONE else None
    latest = parse_iso_timestamp(latest_activity_at)
    elapsed = (now - latest).total_seconds()
    if elapsed >= stale_kill_after_seconds:
        return WorkerState.FAILED
    if elapsed >= stale_after_seconds and current_state == WorkerState.RUNNING:
        return WorkerState.STALE
    return None

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from swarm_mcp.health import compute_staleness_transition, latest_activity_iso
from swarm_mcp.types import WorkerState


def test_latest_activity_prefers_progress_timestamp() -> None:
    progress = {"updated_at": "2026-01-01T00:00:00+00:00"}
    assert latest_activity_iso("2026-01-01T00:10:00+00:00", progress) == "2026-01-01T00:00:00+00:00"


def test_compute_staleness_transition_marks_stale_and_failed() -> None:
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(seconds=200)).isoformat()
    failed_time = (now - timedelta(seconds=400)).isoformat()

    assert compute_staleness_transition(
        current_state=WorkerState.RUNNING,
        latest_activity_at=stale_time,
        now=now,
        stale_after_seconds=120,
        stale_kill_after_seconds=300,
        has_result=False,
    ) == WorkerState.STALE

    assert compute_staleness_transition(
        current_state=WorkerState.STALE,
        latest_activity_at=failed_time,
        now=now,
        stale_after_seconds=120,
        stale_kill_after_seconds=300,
        has_result=False,
    ) == WorkerState.FAILED

    assert compute_staleness_transition(
        current_state=WorkerState.RUNNING,
        latest_activity_at=stale_time,
        now=now,
        stale_after_seconds=120,
        stale_kill_after_seconds=300,
        has_result=True,
    ) == WorkerState.DONE

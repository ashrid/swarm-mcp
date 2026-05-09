from __future__ import annotations

from pathlib import Path

from swarm_mcp.tracking import CostTracker, HistoryTracker, SnapshotManager
from swarm_mcp.types import CostEntry, Priority, ProviderKind, Role, WorkerStatus, WorkerTask
from swarm_mcp.workspace import WorkspaceManager


def test_history_tracker_logs_events(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    history = HistoryTracker(workspace)
    history.log_event("spawn", {"agent_id": "w1"})
    events = history.read_timeline()
    assert events[-1]["event"] == "spawn"


def test_snapshot_manager_round_trip(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    snapshots = SnapshotManager(workspace)
    status = WorkerStatus(
        agent_id="w1",
        provider=ProviderKind.OPENCODE,
        role=Role.WORKER,
        priority=Priority.NORMAL,
    )
    task = WorkerTask(agent_id="w1", provider=ProviderKind.OPENCODE, prompt="analyze")
    snapshots.create(status, task)
    loaded = snapshots.read("w1")
    assert loaded is not None
    assert loaded.agent_id == "w1"


def test_cost_tracker_summary(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    tracker = CostTracker(workspace)
    tracker.add(
        CostEntry(
            agent_id="w1",
            model="kimi",
            provider=ProviderKind.OPENCODE,
            estimated_cost=1.25,
        )
    )
    summary = tracker.summary()
    assert summary["total_cost"] == 1.25

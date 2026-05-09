from __future__ import annotations

from pathlib import Path

from swarm_mcp.archive import ArchiveManager
from swarm_mcp.reporting import ReportingService
from swarm_mcp.tracking import CostTracker, HistoryTracker
from swarm_mcp.types import CostEntry, ProviderKind
from swarm_mcp.workspace import WorkspaceManager


def test_reporting_service_generates_stats(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    history = HistoryTracker(workspace)
    costs = CostTracker(workspace)
    history.log_event("swarm_spawn", {"agent_id": "w1"})
    costs.add(
        CostEntry(
            agent_id="w1",
            model="kimi",
            provider=ProviderKind.OPENCODE,
            estimated_cost=0.5,
        )
    )
    reporting = ReportingService(history=history, costs=costs)
    stats = reporting.stats()
    assert stats["spawn_count"] == 1
    assert stats["total_cost"] == 0.5


def test_reporting_recommends_model_for_category(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    history = HistoryTracker(workspace)
    costs = CostTracker(workspace)
    reporting = ReportingService(history=history, costs=costs)

    history.log_event(
        "swarm_spawn",
        {
            "agent_id": "w1",
            "provider": "opencode",
            "model": "kimi-for-coding",
            "task": "audit authentication and authorization",
        },
    )
    history.log_event(
        "swarm_collect",
        {
            "agent_id": "w1",
            "result": {"confidence": 0.8},
        },
    )
    assert (
        reporting.recommend_model("audit auth paths", fallback="default-model")
        == "kimi-for-coding"
    )


def test_archive_manager_writes_markdown(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    wiki_dir = tmp_path / "wiki"
    archive = ArchiveManager(workspace=workspace, wiki_archive_dir=str(wiki_dir))
    output_path = archive.archive_to_markdown()
    assert output_path is not None
    assert output_path.exists()
    assert output_path.suffix == ".md"


def test_cost_tracker_accumulates_multiple_entries(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    tracker = CostTracker(workspace)
    tracker.add(
        CostEntry(
            agent_id="w1",
            model="kimi",
            provider=ProviderKind.OPENCODE,
            estimated_cost=1.0,
        )
    )
    tracker.add(
        CostEntry(
            agent_id="w1",
            model="kimi",
            provider=ProviderKind.OPENCODE,
            estimated_cost=0.5,
        )
    )
    summary = tracker.summary()
    assert summary["total_cost"] == 1.5
    assert summary["by_provider"]["opencode"] == 1.5

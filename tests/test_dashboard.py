from __future__ import annotations

from pathlib import Path

from swarm_mcp.reporting import ReportingService
from swarm_mcp.tracking import CostTracker, HistoryTracker
from swarm_mcp.workspace import WorkspaceManager


def test_render_dashboard_text_includes_workers_and_queue(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    reporting = ReportingService(history=HistoryTracker(workspace), costs=CostTracker(workspace))
    text = reporting.render_dashboard_text(
        workers=[
            {
                "agent_id": "w1",
                "state": "running",
                "provider": "opencode",
                "model": "kimi-for-coding",
                "priority": "normal",
                "alive": True,
            }
        ],
        queue_depth_by_provider={"opencode": 2},
    )
    assert "SWARM DASHBOARD" in text
    assert "w1 | running | opencode" in text
    assert "opencode: 2" in text

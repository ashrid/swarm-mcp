from __future__ import annotations

import json
from pathlib import Path

from swarm_mcp.dashboard_renderer import render_dashboard


def test_render_dashboard_empty(tmp_path: Path) -> None:
    swarm_dir = tmp_path / ".swarm"
    swarm_dir.mkdir()
    output = render_dashboard(swarm_dir)
    assert "SWARM DASHBOARD" in output
    assert "Workers: 0" in output


def test_render_dashboard_with_workers(tmp_path: Path) -> None:
    swarm_dir = tmp_path / ".swarm"
    swarm_dir.mkdir()
    registry = {
        "workers": [
            {"agent_id": "worker-1", "state": "running", "provider": "opencode",
             "model": "kimi", "priority": "normal"},
            {"agent_id": "worker-2", "state": "pending", "provider": "claude_code",
             "model": None, "priority": "high"},
        ]
    }
    (swarm_dir / "registry.json").write_text(json.dumps(registry))
    output = render_dashboard(swarm_dir)
    assert "worker-1" in output
    assert "worker-2" in output
    assert "running" in output
    assert "pending" in output
    assert "opencode" in output
    assert "claude_code" in output
    assert "Queue depth by provider:" in output
    assert "claude_code: 1" in output


def test_render_dashboard_with_costs(tmp_path: Path) -> None:
    swarm_dir = tmp_path / ".swarm"
    costs_dir = swarm_dir / "costs"
    costs_dir.mkdir(parents=True)
    costs = {
        "entries": [
            {"estimated_cost": 0.0042, "provider": "opencode"},
            {"estimated_cost": 0.0013, "provider": "claude_code"},
        ]
    }
    (costs_dir / "current.json").write_text(json.dumps(costs))
    output = render_dashboard(swarm_dir)
    assert "Total cost: $0.0055" in output

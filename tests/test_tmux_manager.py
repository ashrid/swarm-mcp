from __future__ import annotations

from swarm_mcp.tmux_manager import MockTmuxManager


def test_mock_tmux_manager_worker_lifecycle() -> None:
    tmux = MockTmuxManager(session_name="swarm-test")
    pane_id = tmux.spawn_worker("worker-1", "python -m worker")

    assert pane_id == "swarm-test:worker-1"
    assert tmux.is_alive("worker-1") is True

    tmux.send_keys("worker-1", "hello")
    captured = tmux.capture_pane("worker-1")
    assert "python -m worker" in captured
    assert "hello" in captured

    tmux.kill_worker("worker-1")
    assert tmux.is_alive("worker-1") is False

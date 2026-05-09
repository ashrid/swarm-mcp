from __future__ import annotations

from pathlib import Path

from swarm_mcp.config import SwarmConfig
from swarm_mcp.types import ProviderKind, WorkerState
from swarm_mcp.workspace import WorkspaceManager


def test_worker_state_enum_values() -> None:
    assert WorkerState.RUNNING.value == "running"
    assert WorkerState.STALE.value == "stale"


def test_default_config_can_be_created(tmp_path: Path) -> None:
    config_path = tmp_path / ".swarm" / "config.yaml"
    config = SwarmConfig.load(config_path, workspace_root=str(tmp_path))
    assert config.providers[ProviderKind.OPENCODE].command == "opencode"
    assert config_path.exists()


def test_workspace_manager_ensures_structure(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    assert (tmp_path / ".swarm" / "agents").exists()
    assert (tmp_path / ".swarm" / "results").exists()
    assert (tmp_path / ".swarm" / "registry.json").exists()


def test_workspace_manager_main_lock_round_trip(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    workspace.write_main_lock(pid=12345)
    payload = workspace.read_main_lock()
    assert payload is not None
    assert payload["pid"] == 12345

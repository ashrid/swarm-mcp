from __future__ import annotations

import asyncio
from pathlib import Path

from swarm_mcp.config import SwarmConfig
from swarm_mcp.provider_router import ProviderRouter
from swarm_mcp.registry import WorkerRegistry
from swarm_mcp.templates import WorkerConfigRenderer
from swarm_mcp.types import Priority, ProviderKind, Role, WorkerState, WorkerStatus, WorkerTask
from swarm_mcp.workspace import WorkspaceManager


def test_provider_router_builds_opencode_command(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    config = SwarmConfig.default(str(tmp_path))
    router = ProviderRouter(config, str(tmp_path))
    task = WorkerTask(
        agent_id="worker-1",
        provider=ProviderKind.OPENCODE,
        prompt="analyze auth",
        model="kimi-for-coding",
    )
    spawn = router.build(task)
    assert "swarm_mcp.worker_runner" in spawn.command
    assert "opencode" in spawn.raw_command
    assert (
        "--model 'kimi-for-coding'" in spawn.raw_command
        or '--model "kimi-for-coding"' in spawn.raw_command
        or "--model kimi-for-coding" in spawn.raw_command
    )
    assert spawn.env["SWARM_AGENT_ID"] == "worker-1"


def test_renderer_writes_worker_files(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    renderer = WorkerConfigRenderer(workspace)
    task = WorkerTask(agent_id="worker-1", provider=ProviderKind.OPENCODE, prompt="analyze auth")
    rendered = renderer.render_all(task)
    assert workspace.agent_file("worker-1").exists()
    assert workspace.settings_file("worker-1").exists()
    assert workspace.permissions_file("worker-1").exists()
    assert workspace.mcp_config_file("worker-1").exists()
    assert rendered.agents_md_path.endswith("worker-1.md")


def test_registry_persists_worker(tmp_path: Path) -> None:
    async def run() -> None:
        workspace = WorkspaceManager(tmp_path)
        workspace.ensure()
        registry = WorkerRegistry(workspace)
        await registry.load()
        status = WorkerStatus(
            agent_id="worker-1",
            provider=ProviderKind.OPENCODE,
            state=WorkerState.RUNNING,
            role=Role.WORKER,
            priority=Priority.NORMAL,
        )
        task = WorkerTask(
            agent_id="worker-1",
            provider=ProviderKind.OPENCODE,
            prompt="analyze auth",
        )
        await registry.register(status, task)
        loaded = await registry.get("worker-1")
        assert loaded.status.agent_id == "worker-1"
        assert loaded.task is not None

    asyncio.run(run())


def test_registry_allows_pending_status_round_trip(tmp_path: Path) -> None:
    async def run() -> None:
        workspace = WorkspaceManager(tmp_path)
        workspace.ensure()
        registry = WorkerRegistry(workspace)
        await registry.load()
        status = WorkerStatus(
            agent_id="worker-pending",
            provider=ProviderKind.OPENCODE,
            state=WorkerState.PENDING,
            role=Role.WORKER,
            priority=Priority.NORMAL,
        )
        task = WorkerTask(
            agent_id="worker-pending",
            provider=ProviderKind.OPENCODE,
            prompt="analyze auth",
        )
        await registry.register(status, task)
        loaded = await registry.get("worker-pending")
        assert loaded.status.state == WorkerState.PENDING

    asyncio.run(run())

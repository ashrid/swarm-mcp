from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from swarm_mcp.archive import ArchiveManager
from swarm_mcp.config import SwarmConfig
from swarm_mcp.message_queue import MessageQueue
from swarm_mcp.provider_router import ProviderRouter
from swarm_mcp.registry import WorkerRegistry
from swarm_mcp.reporting import ReportingService
from swarm_mcp.server import (
    AppContext,
    _claim_main_lock,
    _dispatch_queue_for_provider,
    _process_result_file,
)
from swarm_mcp.templates import WorkerConfigRenderer
from swarm_mcp.tmux_manager import TmuxManager
from swarm_mcp.tracking import CostTracker, HistoryTracker, SnapshotManager
from swarm_mcp.types import Priority, ProviderKind, Role, WorkerState, WorkerStatus, WorkerTask
from swarm_mcp.workspace import WorkspaceManager


async def build_app_context(tmp_path: Path) -> AppContext:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure()
    config = SwarmConfig.default(str(tmp_path))
    registry = WorkerRegistry(workspace)
    await registry.load()
    queue = MessageQueue()
    router = ProviderRouter(config=config, workspace_root=str(tmp_path))
    renderer = WorkerConfigRenderer(workspace)
    history = HistoryTracker(workspace)
    snapshots = SnapshotManager(workspace)
    costs = CostTracker(workspace)
    reporting = ReportingService(history=history, costs=costs)
    archive = ArchiveManager(workspace=workspace, wiki_archive_dir=None)
    tmux = TmuxManager(session_name=workspace.session_name, mock=True)
    return AppContext(
        config=config,
        workspace=workspace,
        tmux=tmux,
        registry=registry,
        queue=queue,
        router=router,
        renderer=renderer,
        history=history,
        snapshots=snapshots,
        costs=costs,
        reporting=reporting,
        archive=archive,
        orchestration_enabled=True,
    )


def test_process_result_file_marks_done(tmp_path: Path) -> None:
    async def run() -> None:
        app = await build_app_context(tmp_path)
        status = WorkerStatus(
            agent_id="worker-1",
            task_id="task-1",
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
        await app.registry.register(status, task)
        app.workspace.write_json(
            app.workspace.result_file("worker-1"),
            {
                "task_id": "task-1",
                "agent_id": "worker-1",
                "output": "RESULT: done",
                "exit_code": 0,
            },
        )
        payload = await _process_result_file(app, "worker-1")
        assert payload is not None
        loaded = await app.registry.get("worker-1")
        assert loaded.status.state == WorkerState.DONE

    asyncio.run(run())


def test_process_result_file_marks_failed_on_nonzero_exit(tmp_path: Path) -> None:
    async def run() -> None:
        app = await build_app_context(tmp_path)
        status = WorkerStatus(
            agent_id="worker-1",
            task_id="task-1",
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
        await app.registry.register(status, task)
        app.workspace.write_json(
            app.workspace.result_file("worker-1"),
            {
                "task_id": "task-1",
                "agent_id": "worker-1",
                "output": "permission denied",
                "exit_code": 1,
            },
        )
        payload = await _process_result_file(app, "worker-1")
        assert payload is not None
        assert payload["failure_class"] == "permission_denied"
        loaded = await app.registry.get("worker-1")
        assert loaded.status.state == WorkerState.FAILED

    asyncio.run(run())


def test_dispatch_queue_launches_pending_worker_when_capacity_available(tmp_path: Path) -> None:
    async def run() -> None:
        app = await build_app_context(tmp_path)
        pending_status = WorkerStatus(
            agent_id="queued-1",
            task_id="task-1",
            provider=ProviderKind.OPENCODE,
            state=WorkerState.PENDING,
            role=Role.WORKER,
            priority=Priority.NORMAL,
        )
        task = WorkerTask(
            agent_id="queued-1",
            provider=ProviderKind.OPENCODE,
            prompt="analyze auth",
        )
        await app.registry.register(pending_status, task)
        launched = await _dispatch_queue_for_provider(app, ProviderKind.OPENCODE)
        assert len(launched) == 1
        loaded = await app.registry.get("queued-1")
        assert loaded.status.state == WorkerState.RUNNING
        assert app.tmux.is_alive("queued-1") is True

    asyncio.run(run())


def test_claim_main_re_enables_orchestration_after_conflict(tmp_path: Path) -> None:
    async def run() -> None:
        app = await build_app_context(tmp_path)
        app.workspace.write_main_lock(pid=999999)
        app.orchestration_enabled = False
        result = _claim_main_lock(app, force=True)
        assert result["status"] == "ok"
        assert app.orchestration_enabled is True

    asyncio.run(run())


def test_worker_runner_context_and_result_dispatch(tmp_path: Path) -> None:
    async def run() -> None:
        app = await build_app_context(tmp_path)

        first_task = WorkerTask(
            agent_id="worker-1",
            provider=ProviderKind.OPENCODE,
            prompt="analyze auth",
            model="kimi-for-coding",
        )
        render_info = app.renderer.render_all(first_task)
        runtime_prompt = app.renderer.render_runtime_prompt(first_task)
        spawn = app.router.build(
            first_task,
            prompt_text=runtime_prompt,
            opencode_config_content=json.dumps(
                app.renderer.render_opencode_runtime_config(first_task)
            ),
            generated_paths={
                "SWARM_AGENTS_MD_PATH": render_info.agents_md_path,
                "SWARM_SETTINGS_PATH": render_info.settings_path,
                "SWARM_PERMISSIONS_PATH": render_info.permissions_path,
                "SWARM_MCP_CONFIG_PATH": render_info.mcp_config_path,
            },
        )

        running_status = WorkerStatus(
            agent_id="worker-1",
            task_id=first_task.task_id,
            provider=ProviderKind.OPENCODE,
            state=WorkerState.RUNNING,
            role=Role.WORKER,
            priority=Priority.NORMAL,
        )
        await app.registry.register(running_status, first_task)

        queued_status = WorkerStatus(
            agent_id="worker-2",
            task_id="task-2",
            provider=ProviderKind.OPENCODE,
            state=WorkerState.PENDING,
            role=Role.WORKER,
            priority=Priority.NORMAL,
        )
        queued_task = WorkerTask(
            agent_id="worker-2",
            provider=ProviderKind.OPENCODE,
            prompt="follow up",
        )
        await app.registry.register(queued_status, queued_task)

        provider_command = (
            f"{sys.executable} -c \"import os; "
            "print(os.environ['SWARM_TASK']); "
            "print(os.environ['SWARM_AGENTS_MD_PATH'])\""
        )
        runner_command = [
            sys.executable,
            "-m",
            "swarm_mcp.worker_runner",
            "--agent-id",
            first_task.agent_id,
            "--task-id",
            first_task.task_id,
            "--result-file",
            str(app.workspace.result_file(first_task.agent_id)),
            "--command",
            provider_command,
        ]
        env = os.environ.copy()
        env.update(spawn.env)
        completed = subprocess.run(
            runner_command,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        assert "analyze auth" in completed.stdout
        assert render_info.agents_md_path in completed.stdout

        payload = await _process_result_file(app, first_task.agent_id)
        assert payload is not None
        loaded_first = await app.registry.get(first_task.agent_id)
        loaded_second = await app.registry.get(queued_task.agent_id)
        assert loaded_first.status.state == WorkerState.DONE
        assert loaded_second.status.state == WorkerState.RUNNING

    asyncio.run(run())


def test_process_result_file_marks_failed_when_budget_exceeded(tmp_path: Path) -> None:
    async def run() -> None:
        app = await build_app_context(tmp_path)
        status = WorkerStatus(
            agent_id="worker-1",
            task_id="task-1",
            provider=ProviderKind.OPENCODE,
            state=WorkerState.RUNNING,
            role=Role.WORKER,
            priority=Priority.NORMAL,
            budget_spent=5.0,
        )
        task = WorkerTask(
            agent_id="worker-1",
            provider=ProviderKind.OPENCODE,
            prompt="analyze auth",
            budget_limit=5.0,
        )
        await app.registry.register(status, task)
        app.workspace.write_json(
            app.workspace.result_file("worker-1"),
            {
                "task_id": "task-1",
                "agent_id": "worker-1",
                "output": "Done. Cost: $0.01",
                "exit_code": 0,
            },
        )
        payload = await _process_result_file(app, "worker-1")
        assert payload is not None
        assert payload.get("failure_class") == "budget_exceeded"
        assert payload.get("exit_code") == 1
        loaded = await app.registry.get("worker-1")
        assert loaded.status.state == WorkerState.FAILED

    asyncio.run(run())

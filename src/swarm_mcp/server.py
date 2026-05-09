"""FastMCP server scaffold for swarm-mcp."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import Context, FastMCP

from .archive import ArchiveManager
from .config import SwarmConfig
from .health import compute_staleness_transition, latest_activity_iso
from .logging import configure_logging
from .message_queue import MessageQueue
from .planner import decompose_task, normalize_task, task_similarity
from .provider_router import ProviderRouter
from .registry import WorkerRegistry
from .reporting import ReportingService
from .templates import WorkerConfigRenderer
from .tmux_manager import TmuxManager
from .tracking import CostTracker, HistoryTracker, SnapshotManager
from .types import (
    CostEntry,
    FailureClass,
    Priority,
    ProviderKind,
    Role,
    WorkerState,
    WorkerStatus,
    WorkerTask,
)
from .workspace import WorkspaceManager

logger = configure_logging()


def _result_path(app: AppContext, agent_id: str) -> Path:
    return app.workspace.result_file(agent_id)


def _write_result_file(app: AppContext, result: dict[str, Any], agent_id: str) -> None:
    _result_path(app, agent_id).write_text(json.dumps(result, indent=2), encoding="utf-8")


def _read_progress_payload(app: AppContext, agent_id: str) -> dict[str, Any] | None:
    progress_path = app.workspace.progress_file(agent_id)
    if not progress_path.exists():
        return None
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _classify_failure(record: WorkerStatus, output_text: str) -> FailureClass:
    lowered = output_text.lower()
    if "denied" in lowered or "permission" in lowered:
        return FailureClass.PERMISSION_DENIED
    if "rate limit" in lowered or "429" in lowered:
        return FailureClass.PROVIDER_ERROR
    if "timeout" in lowered or record.state == WorkerState.STALE:
        return FailureClass.TIMEOUT if record.state != WorkerState.STALE else FailureClass.STALE
    if "context" in lowered or "token" in lowered:
        return FailureClass.CONTEXT_OVERFLOW
    return FailureClass.UNKNOWN


def _retry_suggestion(failure: FailureClass) -> str:
    if failure == FailureClass.PERMISSION_DENIED:
        return "Consider approving the path or reducing external access requirements."
    if failure == FailureClass.PROVIDER_ERROR:
        return "Consider switching provider or reducing concurrency for this provider."
    if failure == FailureClass.TIMEOUT:
        return "Consider increasing max_duration or splitting the task."
    if failure == FailureClass.STALE:
        return "Consider switching model/provider or sending corrective guidance before retrying."
    if failure == FailureClass.CONTEXT_OVERFLOW:
        return "Consider decomposing the task into smaller subtasks."
    return "Review logs and worker output before retrying."


async def _record_worker_cost(
    app: AppContext,
    agent_id: str,
    amount: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict[str, Any]:
    record = await app.registry.get(agent_id)
    entry = CostEntry(
        agent_id=agent_id,
        model=record.status.model or "default",
        provider=record.status.provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=amount,
    )
    app.costs.add(entry)
    updated_status = await app.registry.update_status(
        agent_id,
        budget_spent=record.status.budget_spent + amount,
    )
    budget_limit = record.task.budget_limit if record.task else None
    exceeded = budget_limit is not None and updated_status.budget_spent >= budget_limit
    if exceeded and app.tmux.is_alive(agent_id):
        app.tmux.kill_worker(agent_id)
        await app.registry.update_status(agent_id, state=WorkerState.FAILED)
        app.history.log_event(
            "swarm_budget_exceeded",
            {
                "agent_id": agent_id,
                "budget_spent": updated_status.budget_spent,
                "budget_limit": budget_limit,
            },
        )
    return {
        "agent_id": agent_id,
        "budget_spent": updated_status.budget_spent,
        "budget_limit": budget_limit,
        "budget_exceeded": exceeded,
    }


async def _process_result_file(app: AppContext, agent_id: str) -> dict[str, Any] | None:
    result_path = app.workspace.result_file(agent_id)
    if not result_path.exists():
        return None
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    record = await app.registry.get(agent_id)
    exit_code_raw = payload.get("exit_code")
    if not isinstance(exit_code_raw, int):
        payload["failure_class"] = FailureClass.UNKNOWN.value
        await app.registry.update_status(agent_id, state=WorkerState.FAILED)
        app.history.log_event(
            "swarm_failed",
            {"agent_id": agent_id, "reason": "missing_or_invalid_exit_code"},
        )
        await _dispatch_queue_for_provider(app, record.status.provider)
        return payload
    exit_code = exit_code_raw
    output_text = str(payload.get("output", ""))
    if exit_code == 0:
        await app.registry.update_status(agent_id, state=WorkerState.DONE)
        app.history.log_event("swarm_complete", {"agent_id": agent_id, "exit_code": exit_code})
        await _dispatch_queue_for_provider(app, record.status.provider)
    else:
        failure = _classify_failure(record.status, output_text)
        payload["failure_class"] = failure.value
        await app.registry.update_status(agent_id, state=WorkerState.FAILED)
        app.history.log_event(
            "swarm_failed",
            {"agent_id": agent_id, "exit_code": exit_code, "failure_class": failure.value},
        )
        await _dispatch_queue_for_provider(app, record.status.provider)
    return payload


async def _dispatch_queue_for_provider(
    app: AppContext,
    provider_filter: ProviderKind | None,
) -> list[dict[str, Any]]:
    launched: list[dict[str, Any]] = []
    records = await app.registry.list()
    for record in records:
        if record.status.state != WorkerState.PENDING or record.task is None:
            continue
        if provider_filter and record.status.provider != provider_filter:
            continue
        provider_config = app.config.providers[record.status.provider]
        current = await app.registry.list()
        active = [
            item
            for item in current
            if item.status.provider == record.status.provider
            and item.status.state == WorkerState.RUNNING
        ]
        if len(active) >= provider_config.max_workers:
            continue
        await app.registry.remove(record.status.agent_id)
        launched.append(await _launch_worker(app, record.task))
    return launched


def _startup_main_lock_status(app: AppContext) -> tuple[str, dict[str, object] | None]:
    existing = app.workspace.read_main_lock()
    current_pid = os.getpid()
    if not existing:
        app.workspace.write_main_lock(pid=current_pid)
        return ("claimed", None)
    existing_pid = existing.get("pid")
    if isinstance(existing_pid, (int, str)) and int(existing_pid) == current_pid:
        app.workspace.write_main_lock(pid=current_pid)
        return ("claimed", existing)
    if isinstance(existing_pid, (int, str)) and not _pid_is_alive(int(existing_pid)):
        app.workspace.write_main_lock(pid=current_pid)
        return ("claimed", existing)
    return ("conflict", existing)


def _claim_main_lock(app: AppContext, force: bool) -> dict[str, Any]:
    existing = app.workspace.read_main_lock()
    current_pid = os.getpid()
    if existing and not force:
        existing_pid = existing.get("pid")
        if isinstance(existing_pid, (int, str)) and int(existing_pid) != current_pid:
            return {
                "status": "conflict",
                "message": "main lock already held for this workspace",
                "existing": existing,
            }
    app.workspace.write_main_lock(pid=current_pid)
    app.orchestration_enabled = True
    app.history.log_event(
        "swarm_claim_main",
        {"pid": current_pid, "forced": force, "workspace": str(app.workspace.root)},
    )
    return {
        "status": "ok",
        "pid": current_pid,
        "workspace": str(app.workspace.root),
        "forced": force,
    }


def _require_orchestration_enabled(app: AppContext) -> None:
    if not app.orchestration_enabled:
        raise RuntimeError(
            "MAIN lock is already held for this workspace. This session is in standalone mode; "
            "call swarm_claim_main(force=True) to take control intentionally."
        )


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _health_monitor(app: AppContext) -> None:
    while True:
        records = await app.registry.list()
        now = datetime.now(timezone.utc)
        for record in records:
            if record.status.state not in {WorkerState.RUNNING, WorkerState.STALE}:
                continue
            progress_payload = _read_progress_payload(app, record.status.agent_id)
            latest_iso = latest_activity_iso(record.status.updated_at, progress_payload)
            result_exists = app.workspace.result_file(record.status.agent_id).exists()
            transition = compute_staleness_transition(
                current_state=record.status.state,
                latest_activity_at=latest_iso,
                now=now,
                stale_after_seconds=app.config.thresholds.stale_after_seconds,
                stale_kill_after_seconds=app.config.thresholds.stale_kill_after_seconds,
                has_result=result_exists,
            )
            if transition is None:
                continue
            if transition == WorkerState.DONE:
                await _process_result_file(app, record.status.agent_id)
                await _dispatch_queue_for_provider(app, record.status.provider)
                continue
            if transition == WorkerState.STALE:
                await app.registry.update_status(record.status.agent_id, state=WorkerState.STALE)
                if app.tmux.is_alive(record.status.agent_id):
                    thinking = app.tmux.capture_pane(record.status.agent_id)
                    thinking_path = app.workspace.swarm_dir.joinpath(
                        "thinking",
                        f"{record.status.agent_id}.md",
                    )
                    thinking_path.write_text(
                        thinking,
                        encoding="utf-8",
                    )
                app.history.log_event("swarm_stale", {"agent_id": record.status.agent_id})
                continue
            if transition == WorkerState.FAILED:
                if app.tmux.is_alive(record.status.agent_id):
                    app.tmux.kill_worker(record.status.agent_id)
                await app.registry.update_status(record.status.agent_id, state=WorkerState.FAILED)
                app.history.log_event(
                    "swarm_failed",
                    {"agent_id": record.status.agent_id, "reason": "stale_timeout"},
                )
                await _dispatch_queue_for_provider(app, record.status.provider)
        await asyncio.sleep(5)


async def _launch_worker(app: AppContext, worker_task: WorkerTask) -> dict[str, Any]:
    render_info = app.renderer.render_all(worker_task)
    runtime_prompt = app.renderer.render_runtime_prompt(worker_task)
    opencode_runtime_config = json.dumps(
        app.renderer.render_opencode_runtime_config(worker_task),
        indent=2,
    )
    spawn = app.router.build(
        worker_task,
        prompt_text=runtime_prompt,
        opencode_config_content=opencode_runtime_config,
        generated_paths={
            "SWARM_AGENTS_MD_PATH": render_info.agents_md_path,
            "SWARM_SETTINGS_PATH": render_info.settings_path,
            "SWARM_PERMISSIONS_PATH": render_info.permissions_path,
            "SWARM_MCP_CONFIG_PATH": render_info.mcp_config_path,
        },
    )
    env_prefix = " ".join(
        f"{key}={sh_quote(value)}" for key, value in spawn.env.items()
    )
    prefixed_command = f"{env_prefix} {spawn.command}"
    pane_id = app.tmux.spawn_worker(worker_task.agent_id, prefixed_command)
    status = WorkerStatus(
        agent_id=worker_task.agent_id,
        task_id=worker_task.task_id,
        state=WorkerState.RUNNING,
        role=Role.WORKER,
        model=worker_task.model,
        provider=worker_task.provider,
        priority=worker_task.priority,
        preemptible=worker_task.preemptible,
        pane_id=pane_id,
        session_name=app.workspace.session_name,
    )
    app.snapshots.create(status, worker_task)
    await app.registry.register(status=status, task=worker_task)
    app.queue.publish_task(worker_task)
    app.history.log_event(
        "swarm_spawn",
        {
            "agent_id": worker_task.agent_id,
            "provider": worker_task.provider.value,
            "task_id": worker_task.task_id,
            "model": worker_task.model,
            "skills": worker_task.skills,
            "task": worker_task.prompt,
        },
    )
    return {
        "status": "ok",
        "agent_id": worker_task.agent_id,
        "task_id": worker_task.task_id,
        "pane_id": pane_id,
        "command": spawn.command,
        "provider_command": spawn.raw_command,
        "generated": render_info.model_dump(mode="json"),
    }


@dataclass
class AppContext:
    config: SwarmConfig
    workspace: WorkspaceManager
    tmux: TmuxManager
    registry: WorkerRegistry
    queue: MessageQueue
    router: ProviderRouter
    renderer: WorkerConfigRenderer
    history: HistoryTracker
    snapshots: SnapshotManager
    costs: CostTracker
    reporting: ReportingService
    archive: ArchiveManager
    orchestration_enabled: bool


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
    workspace_root = str(Path.cwd())
    workspace = WorkspaceManager(workspace_root)
    workspace.ensure()
    config = SwarmConfig.load(workspace.swarm_dir / "config.yaml", workspace_root=workspace_root)
    tmux = TmuxManager(session_name=workspace.session_name, mock=False)
    registry = WorkerRegistry(workspace)
    await registry.load()
    queue = MessageQueue()
    router = ProviderRouter(config=config, workspace_root=workspace_root)
    renderer = WorkerConfigRenderer(workspace)
    history = HistoryTracker(workspace)
    snapshots = SnapshotManager(workspace)
    costs = CostTracker(workspace)
    reporting = ReportingService(history=history, costs=costs)
    archive = ArchiveManager(workspace=workspace, wiki_archive_dir=config.wiki_archive_dir)
    app_context = AppContext(
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
    lock_status, lock_existing = _startup_main_lock_status(app_context)
    app_context.orchestration_enabled = lock_status != "conflict"
    health_task = asyncio.create_task(_health_monitor(app_context))
    logger.info("Swarm MCP starting for workspace %s", workspace_root)
    if lock_status == "conflict":
        logger.warning("MAIN lock already held for workspace %s: %s", workspace_root, lock_existing)
    try:
        yield app_context
    finally:
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        current_lock = workspace.read_main_lock()
        if current_lock and current_lock.get("pid") == os.getpid():
            workspace.clear_main_lock()
        logger.info("Swarm MCP shutting down for workspace %s", workspace_root)


mcp = FastMCP("swarm-mcp", lifespan=lifespan)


@mcp.tool()
def swarm_ping() -> dict[str, str]:
    """Basic liveness tool for initial scaffolding verification."""
    return {"status": "ok", "server": "swarm-mcp"}


@mcp.tool()
async def swarm_whoami(ctx: Context[Any, AppContext]) -> dict[str, str]:
    """Return the current workspace and tmux session for this MCP process."""
    app: AppContext = ctx.request_context.lifespan_context
    lock_info = app.workspace.read_main_lock() or {}
    return {
        "role": "main" if app.orchestration_enabled else "standalone",
        "workspace": str(app.workspace.root),
        "swarm_dir": str(app.workspace.swarm_dir),
        "session_name": app.workspace.session_name,
        "lock_pid": str(lock_info.get("pid", "")),
    }


@mcp.tool()
async def swarm_claim_main(
    ctx: Context[Any, AppContext],
    force: bool = False,
) -> dict[str, Any]:
    """Claim the MAIN role for the current workspace by writing the lock file."""
    app: AppContext = ctx.request_context.lifespan_context
    return _claim_main_lock(app, force)


@mcp.tool()
async def swarm_init(ctx: Context[Any, AppContext], force: bool = False) -> dict[str, Any]:
    """Bootstrap the .swarm workspace structure and default config files."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    if app.workspace.swarm_dir.exists() and not force:
        app.workspace.ensure()
        app.config.save(app.workspace.swarm_dir / "config.yaml")
        return {
            "status": "ok",
            "workspace": str(app.workspace.root),
            "swarm_dir": str(app.workspace.swarm_dir),
            "forced": False,
        }
    app.workspace.ensure()
    app.config.save(app.workspace.swarm_dir / "config.yaml")
    app.history.log_event("swarm_init", {"workspace": str(app.workspace.root), "force": force})
    return {
        "status": "ok",
        "workspace": str(app.workspace.root),
        "swarm_dir": str(app.workspace.swarm_dir),
        "forced": force,
    }


@mcp.tool()
async def swarm_spawn(
    ctx: Context[Any, AppContext],
    agent_id: str,
    provider: str,
    task: str,
    model: str | None = None,
    skills: list[str] | None = None,
    mcp_servers: list[str] | None = None,
    priority: str = "normal",
    preemptible: bool = False,
    budget_limit: float | None = None,
    max_lifetime: int = 600,
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    """Spawn a worker with generated configs and a provider-specific command."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    provider_kind = ProviderKind(provider)
    provider_config = app.config.providers[provider_kind]
    costs_summary = app.costs.summary()
    provider_cost_used = float(costs_summary.get("by_provider", {}).get(provider_kind.value, 0.0))
    provider_cost_cap = app.config.budgets.max_cost_per_provider.get(provider_kind.value)
    if provider_cost_cap is not None and provider_cost_used >= provider_cost_cap:
        return {
            "status": "provider_budget_exceeded",
            "provider": provider_kind.value,
            "used": provider_cost_used,
            "cap": provider_cost_cap,
        }

    existing = await app.registry.list()
    normalized_task = normalize_task(task)
    active_for_provider = [
        record
        for record in existing
        if record.status.provider == provider_kind and record.status.state == WorkerState.RUNNING
    ]
    active_states = {WorkerState.PENDING, WorkerState.RUNNING, WorkerState.STALE}
    for record in existing:
        if record.task is None:
            continue
        if record.status.state not in active_states:
            continue
        if not allow_duplicate and normalize_task(record.task.prompt) == normalized_task:
            return {
                "status": "duplicate_task",
                "message": f"Task already running on {record.status.agent_id}",
                "existing_agent_id": record.status.agent_id,
                "existing_task_id": record.task.task_id,
            }
        similarity = task_similarity(record.task.prompt, task)
        if not allow_duplicate and similarity >= 0.8:
            return {
                "status": "similar_task",
                "message": f"Task is highly similar to {record.status.agent_id}",
                "existing_agent_id": record.status.agent_id,
                "existing_task_id": record.task.task_id,
                "similarity": similarity,
            }
    worker_task = WorkerTask(
        agent_id=agent_id,
        provider=provider_kind,
        prompt=task,
        model=(
            app.reporting.recommend_model(task, provider_config.default_model)
            if model == "auto"
            else model or provider_config.default_model
        ),
        skills=skills or [],
        mcp_servers=mcp_servers or ["swarm", "octopoda"],
        priority=Priority(priority),
        preemptible=preemptible,
        budget_limit=budget_limit or app.config.budgets.default_task_budget,
        max_lifetime_seconds=max_lifetime,
    )
    if len(active_for_provider) >= provider_config.max_workers:
        app.renderer.render_all(worker_task)
        queued_status = WorkerStatus(
            agent_id=agent_id,
            task_id=worker_task.task_id,
            state=WorkerState.PENDING,
            role=Role.WORKER,
            model=worker_task.model,
            provider=provider_kind,
            priority=worker_task.priority,
            preemptible=worker_task.preemptible,
            session_name=app.workspace.session_name,
        )
        await app.registry.register(status=queued_status, task=worker_task)
        app.queue.publish_task(worker_task)
        app.history.log_event(
            "swarm_queue",
            {
                "agent_id": agent_id,
                "provider": provider_kind.value,
                "task_id": worker_task.task_id,
                "model": worker_task.model,
                "task": task,
            },
        )
        return {
            "status": "queued",
            "message": f"Provider {provider_kind.value} is at capacity",
            "provider": provider_kind.value,
            "running": len(active_for_provider),
            "max_workers": provider_config.max_workers,
            "agent_id": agent_id,
            "task_id": worker_task.task_id,
        }

    return await _launch_worker(app, worker_task)


@mcp.tool()
async def swarm_broadcast(
    ctx: Context[Any, AppContext],
    task: str,
    providers: list[str] | None = None,
) -> dict[str, Any]:
    """Spawn one worker per provider for the same task."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    provider_names = providers or [provider.value for provider in ProviderKind]
    spawned: list[dict[str, Any]] = []
    for index, provider_name in enumerate(provider_names, start=1):
        response = await swarm_spawn(
            ctx,
            agent_id=f"broadcast-{index}",
            provider=provider_name,
            task=task,
            allow_duplicate=True,
        )
        spawned.append(cast(dict[str, Any], response))
    return {"status": "ok", "spawned": spawned}


@mcp.tool()
async def swarm_dispatch_queue(
    ctx: Context[Any, AppContext],
    provider: str | None = None,
) -> dict[str, Any]:
    """Dispatch queued workers whose provider slots are available."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    provider_filter = ProviderKind(provider) if provider else None
    launched: list[dict[str, Any]] = []
    records = await app.registry.list()

    for record in records:
        if record.status.state != WorkerState.PENDING or record.task is None:
            continue
        if provider_filter and record.status.provider != provider_filter:
            continue
        provider_config = app.config.providers[record.status.provider]
        current = await app.registry.list()
        active = [
            item
            for item in current
            if item.status.provider == record.status.provider
            and item.status.state == WorkerState.RUNNING
        ]
        if len(active) >= provider_config.max_workers:
            continue
        await app.registry.remove(record.status.agent_id)
        launched.append(await _launch_worker(app, record.task))

    return {"status": "ok", "launched": launched}


@mcp.tool()
async def swarm_status(
    ctx: Context[Any, AppContext],
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Return current worker status for one worker or all workers."""
    app: AppContext = ctx.request_context.lifespan_context
    if agent_id:
        record = await app.registry.get(agent_id)
        return {
            "status": "ok",
            "worker": record.status.model_dump(mode="json"),
            "task": record.task.model_dump(mode="json") if record.task else None,
            "progress": _read_progress_payload(app, agent_id),
        }
    records = await app.registry.list()
    return {
        "status": "ok",
        "workers": [
            {
                "worker": record.status.model_dump(mode="json"),
                "task": record.task.model_dump(mode="json") if record.task else None,
                "progress": _read_progress_payload(app, record.status.agent_id),
            }
            for record in records
        ],
    }


@mcp.tool()
async def swarm_send(
    ctx: Context[Any, AppContext],
    agent_id: str,
    message: str,
    priority: str = "normal",
) -> dict[str, Any]:
    """Write a worker message to disk and inject it into the tmux pane."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    await app.registry.get(agent_id)
    payload = {"agent_id": agent_id, "message": message, "priority": priority}
    app.workspace.write_json(app.workspace.message_file(agent_id), payload)
    prefix = "[ALERT] " if priority == "urgent" else ""
    if app.tmux.is_alive(agent_id):
        app.tmux.send_keys(agent_id, f"{prefix}{message}")
    app.history.log_event("swarm_send", payload)
    return {"status": "ok", "delivered": True, "channels": ["file", "tmux"]}


@mcp.tool()
async def swarm_results(
    ctx: Context[Any, AppContext],
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Replay persisted results from disk."""
    app: AppContext = ctx.request_context.lifespan_context
    if agent_id:
        path = app.workspace.result_file(agent_id)
        if not path.exists():
            return {"status": "ok", "results": []}
        payload = await _process_result_file(app, agent_id)
        return {"status": "ok", "results": [payload] if payload else []}

    results: list[dict[str, Any]] = []
    for path in sorted((app.workspace.swarm_dir / "results").glob("*.json")):
        payload = await _process_result_file(app, path.stem)
        if payload:
            results.append(payload)
    return {"status": "ok", "results": results}


@mcp.tool()
async def swarm_collect(
    ctx: Context[Any, AppContext],
    agent_id: str,
    timeout: int = 300,
) -> dict[str, Any]:
    """Collect a worker result from queue or persisted file."""
    app: AppContext = ctx.request_context.lifespan_context
    record = await app.registry.get(agent_id)
    result_path = app.workspace.result_file(agent_id)
    if result_path.exists():
        payload = await _process_result_file(app, agent_id)
        return {"status": "ok", "result": payload}
    try:
        result = await app.queue.collect_result(agent_id, timeout=float(timeout))
    except TimeoutError:
        return {
            "status": "still_running",
            "agent_id": agent_id,
            "worker_state": record.status.state.value,
        }
    payload = result.model_dump(mode="json")
    _write_result_file(app, payload, agent_id)
    await _process_result_file(app, agent_id)
    app.history.log_event("swarm_collect", {"agent_id": agent_id})
    return {"status": "ok", "result": payload}


async def _wait_for_workers(
    app: AppContext,
    agent_ids: list[str],
    timeout: int,
    mode: str,
) -> dict[str, Any]:
    started = asyncio.get_event_loop().time()
    collected: list[dict[str, Any]] = []
    pending = set(agent_ids)
    while pending:
        for agent_id in list(pending):
            path = app.workspace.result_file(agent_id)
            if path.exists():
                payload = await _process_result_file(app, agent_id)
                if payload:
                    collected.append(payload)
                pending.remove(agent_id)
                if mode == "any":
                    return {"status": "ok", "results": collected, "pending": sorted(pending)}
        if not pending:
            break
        if asyncio.get_event_loop().time() - started >= timeout:
            return {"status": "timeout", "results": collected, "pending": sorted(pending)}
        await asyncio.sleep(0.25)
    return {"status": "ok", "results": collected, "pending": []}


@mcp.tool()
async def swarm_wait_any(
    ctx: Context[Any, AppContext],
    agent_ids: list[str],
    timeout: int = 300,
) -> dict[str, Any]:
    app: AppContext = ctx.request_context.lifespan_context
    return await _wait_for_workers(app, agent_ids, timeout, mode="any")


@mcp.tool()
async def swarm_wait_all(
    ctx: Context[Any, AppContext],
    agent_ids: list[str] | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    app: AppContext = ctx.request_context.lifespan_context
    if agent_ids is None:
        records = await app.registry.list()
        agent_ids = [record.status.agent_id for record in records]
    return await _wait_for_workers(app, agent_ids, timeout, mode="all")


@mcp.tool()
async def swarm_retry(
    ctx: Context[Any, AppContext],
    agent_id: str,
    new_provider: str | None = None,
    smart_retry: bool = False,
) -> dict[str, Any]:
    """Retry a worker using the original task and optional provider override."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    record = await app.registry.get(agent_id)
    if record.task is None:
        raise ValueError("Original task not found; cannot retry")
    output_text = ""
    result_path = app.workspace.result_file(agent_id)
    if result_path.exists():
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        output_text = (
            str(result_payload.get("output", ""))
            if isinstance(result_payload, dict)
            else ""
        )
    elif app.tmux.is_alive(agent_id):
        output_text = app.tmux.capture_pane(agent_id)
    failure = _classify_failure(record.status, output_text)
    provider = new_provider or record.task.provider.value
    suggestion = _retry_suggestion(failure)
    if smart_retry and failure == FailureClass.PROVIDER_ERROR and new_provider is None:
        for candidate in ProviderKind:
            if candidate.value != provider:
                provider = candidate.value
                break
    await swarm_terminate(ctx, agent_id)
    retry_count = 1
    while True:
        new_agent_id = f"{agent_id}-retry-{retry_count}"
        try:
            await app.registry.get(new_agent_id)
            retry_count += 1
        except KeyError:
            break
    response = await swarm_spawn(
        ctx,
        agent_id=new_agent_id,
        provider=provider,
        task=record.task.prompt,
        model=record.task.model,
        skills=record.task.skills,
        mcp_servers=record.task.mcp_servers,
        priority=record.task.priority.value,
        preemptible=record.task.preemptible,
        max_lifetime=record.task.max_lifetime_seconds,
        allow_duplicate=True,
    )
    app.history.log_event(
        "swarm_retry",
        {
            "from_agent_id": agent_id,
            "to_agent_id": new_agent_id,
            "provider": provider,
            "failure_class": failure.value,
            "smart_retry": smart_retry,
        },
    )
    payload = cast(dict[str, Any], response)
    payload["failure_class"] = failure.value
    payload["suggestion"] = suggestion
    payload["selected_provider"] = provider
    return payload


@mcp.tool()
async def swarm_ask_permission(
    ctx: Context[Any, AppContext],
    agent_id: str,
    path: str,
    reason: str = "",
    action: str | None = None,
) -> dict[str, Any]:
    """Request or resolve a permission escalation for a worker."""
    app: AppContext = ctx.request_context.lifespan_context
    permissions_path = app.workspace.permissions_file(agent_id)
    current = app.workspace.read_json(permissions_path, {"requests": [], "approved_paths": []})
    if not isinstance(current, dict):
        current = {"requests": [], "approved_paths": []}
    requests = cast(list[dict[str, str]], current.setdefault("requests", []))
    approved_paths = cast(list[str], current.setdefault("approved_paths", []))
    if action is None:
        request = {"path": path, "reason": reason, "status": "pending"}
        requests.append(request)
        app.workspace.write_json(permissions_path, current)
        return {"status": "pending", "request": request}
    if action not in {"allow", "deny"}:
        raise ValueError("action must be allow or deny")
    if action == "allow":
        approved_paths.append(path)
    requests.append({"path": path, "reason": reason, "status": action})
    app.workspace.write_json(permissions_path, current)
    app.history.log_event(
        "swarm_permission",
        {"agent_id": agent_id, "path": path, "reason": reason, "status": action},
    )
    return {"status": action, "path": path}


@mcp.tool()
async def swarm_request_peer(
    ctx: Context[Any, AppContext],
    agent_id: str,
    task: str,
    provider: str | None = None,
) -> dict[str, Any]:
    """Allow a worker to request a peer helper at depth=1."""
    app: AppContext = ctx.request_context.lifespan_context
    record = await app.registry.get(agent_id)
    if record.task is None:
        raise ValueError("Original worker task missing; cannot spawn peer")
    if not record.task.allow_peer_request:
        return {
            "status": "denied",
            "message": "Peer requests are not enabled for this worker.",
        }
    peer_index = 1
    existing = await app.registry.list()
    existing_ids = {item.status.agent_id for item in existing}
    while f"{agent_id}-peer-{peer_index}" in existing_ids:
        peer_index += 1
    peer_id = f"{agent_id}-peer-{peer_index}"
    response = await swarm_spawn(
        ctx,
        agent_id=peer_id,
        provider=provider or record.task.provider.value,
        task=task,
        model=record.task.model,
        skills=record.task.skills,
        mcp_servers=record.task.mcp_servers,
        priority=record.task.priority.value,
        preemptible=record.task.preemptible,
        max_lifetime=record.task.max_lifetime_seconds,
        allow_duplicate=True,
    )
    app.history.log_event(
        "swarm_request_peer",
        {"agent_id": agent_id, "peer_id": peer_id, "task": task},
    )
    return cast(dict[str, Any], response)


@mcp.tool()
async def swarm_decompose(task: str) -> dict[str, Any]:
    """Return a lightweight decomposition for a complex task."""
    return {"status": "ok", "subtasks": decompose_task(task)}


@mcp.tool()
async def swarm_execute(
    ctx: Context[Any, AppContext],
    plan_name: str,
    subtasks: list[dict[str, Any]],
    provider: str = "opencode",
) -> dict[str, Any]:
    """Spawn workers from an approved decomposition plan."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    spawned: list[dict[str, Any]] = []
    for index, subtask in enumerate(subtasks, start=1):
        response = await swarm_spawn(
            ctx,
            agent_id=f"{plan_name}-{index}",
            provider=provider,
            task=str(subtask["task"]),
            allow_duplicate=True,
        )
        spawned.append(response)
    app.history.log_event("swarm_execute", {"plan_name": plan_name, "count": len(spawned)})
    return {"status": "ok", "spawned": spawned}


@mcp.tool()
async def swarm_workflow(
    ctx: Context[Any, AppContext],
    name: str,
    task: str,
    provider: str = "opencode",
    autonomous: bool = False,
) -> dict[str, Any]:
    """Run a named trusted workflow with optional autonomous execution."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    if name == "security_audit":
        subtasks = decompose_task(task)
    elif name == "refactor_review":
        subtasks = decompose_task(f"refactor {task}")
    else:
        subtasks = decompose_task(task)

    if not autonomous:
        return {
            "status": "planned",
            "workflow": name,
            "task": task,
            "subtasks": subtasks,
        }

    result = await swarm_execute(
        ctx,
        plan_name=name,
        subtasks=subtasks,
        provider=provider,
    )
    app.history.log_event(
        "swarm_workflow",
        {"name": name, "task": task, "autonomous": autonomous, "provider": provider},
    )
    return {
        "status": "executing",
        "workflow": name,
        "task": task,
        "result": result,
    }


@mcp.tool()
async def swarm_shutdown(
    ctx: Context[Any, AppContext],
    immediate: bool = False,
    grace_seconds: int | None = None,
) -> dict[str, Any]:
    """Shutdown all workers gracefully or immediately."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    records = await app.registry.list()
    terminated: list[str] = []
    grace = (
        grace_seconds
        if grace_seconds is not None
        else app.config.thresholds.graceful_shutdown_seconds
    )
    for record in records:
        if not app.tmux.is_alive(record.status.agent_id):
            continue
        if not immediate:
            app.tmux.send_keys(record.status.agent_id, "SHUTDOWN")
    if not immediate and grace > 0:
        await asyncio.sleep(min(grace, 30))
    for record in records:
        if not app.tmux.is_alive(record.status.agent_id):
            continue
        app.tmux.kill_worker(record.status.agent_id)
        await app.registry.update_status(record.status.agent_id, state=WorkerState.FAILED)
        terminated.append(record.status.agent_id)
    app.history.log_event("swarm_shutdown", {"terminated": terminated, "immediate": immediate})
    return {"status": "ok", "terminated": terminated, "immediate": immediate}


@mcp.tool()
async def swarm_health(ctx: Context[Any, AppContext]) -> dict[str, Any]:
    """Return current worker health summary."""
    app: AppContext = ctx.request_context.lifespan_context
    records = await app.registry.list()
    workers: list[dict[str, Any]] = []
    for record in records:
        workers.append(
            {
                "agent_id": record.status.agent_id,
                "state": record.status.state.value,
                "alive": app.tmux.is_alive(record.status.agent_id),
                "provider": record.status.provider.value,
                "model": record.status.model,
                "progress": _read_progress_payload(app, record.status.agent_id),
            }
        )
    return {"status": "ok", "workers": workers}


@mcp.tool()
async def swarm_progress(
    ctx: Context[Any, AppContext],
    agent_id: str,
    message: str,
    percent: float,
) -> dict[str, Any]:
    """Update worker progress and refresh its staleness clock."""
    app: AppContext = ctx.request_context.lifespan_context
    progress = {
        "agent_id": agent_id,
        "message": message,
        "percent": percent,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    app.workspace.write_json(app.workspace.progress_file(agent_id), progress)
    await app.registry.update_status(agent_id)
    app.history.log_event("swarm_progress", progress)
    return {"status": "ok", "progress": progress}


@mcp.tool()
async def swarm_costs(ctx: Context[Any, AppContext]) -> dict[str, Any]:
    """Return running cost totals for the workspace."""
    app: AppContext = ctx.request_context.lifespan_context
    return {"status": "ok", **app.costs.summary()}


@mcp.tool()
async def swarm_record_cost(
    ctx: Context[Any, AppContext],
    agent_id: str,
    amount: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict[str, Any]:
    """Record worker cost and enforce per-task budget limits."""
    app: AppContext = ctx.request_context.lifespan_context
    result = await _record_worker_cost(
        app,
        agent_id=agent_id,
        amount=amount,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    app.history.log_event(
        "swarm_record_cost",
        {
            "agent_id": agent_id,
            "amount": amount,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            **result,
        },
    )
    return {"status": "ok", **result}


@mcp.tool()
async def swarm_stats(ctx: Context[Any, AppContext]) -> dict[str, Any]:
    """Return historical swarm stats for the current workspace."""
    app: AppContext = ctx.request_context.lifespan_context
    return {"status": "ok", **app.reporting.stats()}


@mcp.tool()
async def swarm_report(ctx: Context[Any, AppContext]) -> dict[str, Any]:
    """Return a lightweight recommendations report from recorded history."""
    app: AppContext = ctx.request_context.lifespan_context
    return {"status": "ok", **app.reporting.report()}


@mcp.tool()
async def swarm_history(ctx: Context[Any, AppContext]) -> dict[str, Any]:
    """Return the persisted execution timeline."""
    app: AppContext = ctx.request_context.lifespan_context
    return {"status": "ok", "events": app.history.read_timeline()}


@mcp.tool()
async def swarm_dashboard(ctx: Context[Any, AppContext]) -> dict[str, Any]:
    """Return an operator dashboard summary for the whole swarm."""
    app: AppContext = ctx.request_context.lifespan_context
    records = await app.registry.list()
    stats = app.reporting.stats()
    queue_depth_by_provider: dict[str, int] = {}
    workers = [
        {
            "agent_id": record.status.agent_id,
            "state": record.status.state.value,
            "provider": record.status.provider.value,
            "model": record.status.model,
            "priority": record.status.priority.value,
            "alive": app.tmux.is_alive(record.status.agent_id),
            "progress": _read_progress_payload(app, record.status.agent_id),
        }
        for record in records
    ]
    for record in records:
        if record.status.state == WorkerState.PENDING:
            queue_depth_by_provider.setdefault(record.status.provider.value, 0)
            queue_depth_by_provider[record.status.provider.value] += 1
    return {
        "status": "ok",
        "session_name": app.workspace.session_name,
        "workspace": str(app.workspace.root),
        "workers": workers,
        "stats": stats,
        "queue_depth_by_provider": queue_depth_by_provider,
        "text": app.reporting.render_dashboard_text(workers, queue_depth_by_provider),
    }


@mcp.tool()
async def swarm_undo(ctx: Context[Any, AppContext], agent_id: str) -> dict[str, Any]:
    """Return the stored pre-execution snapshot for a worker."""
    app: AppContext = ctx.request_context.lifespan_context
    snapshot = app.snapshots.read(agent_id)
    if snapshot is None:
        return {"status": "not_found", "agent_id": agent_id}
    return {"status": "ok", "snapshot": snapshot.model_dump(mode="json")}


@mcp.tool()
async def swarm_rollback(
    ctx: Context[Any, AppContext],
    to_step: int,
) -> dict[str, Any]:
    """Return the timeline prefix up to a given step for manual rewind workflows."""
    app: AppContext = ctx.request_context.lifespan_context
    events = app.history.read_timeline()
    return {"status": "ok", "events": events[:to_step], "to_step": to_step}


@mcp.tool()
async def swarm_cleanup(
    ctx: Context[Any, AppContext],
    force: bool = False,
) -> dict[str, Any]:
    """Archive the session to markdown and purge transient files."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    archive_path = app.archive.archive_to_markdown()
    if not force and archive_path is None:
        return {
            "status": "needs_archive_path",
            "message": (
                "wiki_archive_dir is not configured; set it in .swarm/config.yaml "
                "or use force=True to purge only."
            ),
        }
    cleanup = app.archive.cleanup_transient_files()
    app.history.log_event(
        "swarm_cleanup",
        {"archive_path": str(archive_path) if archive_path else None, **cleanup},
    )
    return {
        "status": "ok",
        "archive_path": str(archive_path) if archive_path else None,
        **cleanup,
    }


@mcp.tool()
async def swarm_terminate(ctx: Context[Any, AppContext], agent_id: str) -> dict[str, Any]:
    """Terminate a worker and mark its registry entry failed or removed."""
    app: AppContext = ctx.request_context.lifespan_context
    _require_orchestration_enabled(app)
    record = await app.registry.get(agent_id)
    if app.tmux.is_alive(agent_id):
        app.tmux.kill_worker(agent_id)
    await app.registry.update_status(agent_id, state=WorkerState.FAILED)
    app.history.log_event(
        "swarm_terminate",
        {
            "agent_id": agent_id,
            "previous_state": record.status.state.value,
            "provider": record.status.provider.value,
            "model": record.status.model,
            "task": record.task.prompt if record.task else None,
        },
    )
    await swarm_dispatch_queue(ctx, provider=record.status.provider.value)
    return {
        "status": "ok",
        "agent_id": agent_id,
        "previous_state": record.status.state.value,
        "current_state": WorkerState.FAILED.value,
    }


def sh_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def main() -> None:
    mcp.run()

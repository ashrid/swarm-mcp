"""Basic local example using the current swarm-mcp building blocks directly.

This is not an MCP client example yet. It exercises the current Python modules
so the project has a concrete, runnable example while the MCP surface continues
to expand.
"""

from __future__ import annotations

from pathlib import Path

from swarm_mcp.config import SwarmConfig
from swarm_mcp.provider_router import ProviderRouter
from swarm_mcp.reporting import ReportingService
from swarm_mcp.templates import WorkerConfigRenderer
from swarm_mcp.tracking import CostTracker, HistoryTracker
from swarm_mcp.types import ProviderKind, WorkerTask
from swarm_mcp.workspace import WorkspaceManager


def main() -> None:
    workspace = WorkspaceManager(Path.cwd())
    workspace.ensure()

    config = SwarmConfig.load(
        workspace.swarm_dir / "config.yaml",
        workspace_root=str(workspace.root),
    )
    router = ProviderRouter(config, str(workspace.root))
    renderer = WorkerConfigRenderer(workspace)
    history = HistoryTracker(workspace)
    costs = CostTracker(workspace)
    reporting = ReportingService(history=history, costs=costs)

    task = WorkerTask(
        agent_id="example-worker-1",
        provider=ProviderKind.OPENCODE,
        prompt="Analyze the auth module and summarize risks.",
        model="kimi-for-coding",
    )

    rendered = renderer.render_all(task)
    command = router.build(task)
    history.log_event(
        "example_preview",
        {
            "agent_id": task.agent_id,
            "provider": task.provider.value,
            "model": task.model,
        },
    )

    print("Workspace:", workspace.root)
    print("Swarm dir:", workspace.swarm_dir)
    print("Generated files:")
    print("  AGENTS:", rendered.agents_md_path)
    print("  Settings:", rendered.settings_path)
    print("  Permissions:", rendered.permissions_path)
    print("  MCP config:", rendered.mcp_config_path)
    print()
    print("Spawn command preview:")
    print(command.command)
    print()
    print("Spawn env preview:")
    for key, value in command.env.items():
        print(f"  {key}={value}")

    print()
    print("Dashboard preview:")
    print(
        reporting.render_dashboard_text(
            workers=[
                {
                    "agent_id": task.agent_id,
                    "state": "pending",
                    "provider": task.provider.value,
                    "model": task.model,
                    "priority": task.priority.value,
                    "alive": False,
                }
            ],
            queue_depth_by_provider={task.provider.value: 1},
        )
    )


if __name__ == "__main__":
    main()

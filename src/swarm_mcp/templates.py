"""Per-worker file generation from the workspace template."""

from __future__ import annotations

import json
from string import Template
from typing import Any

from .types import RenderedWorkerConfig, Role, WorkerTask
from .workspace import WorkspaceManager


class WorkerConfigRenderer:
    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace

    def render_agents_md(self, task: WorkerTask) -> str:
        template_path = self.workspace.swarm_dir / "agents.md.template"
        template = Template(template_path.read_text(encoding="utf-8"))
        return template.safe_substitute(
            agent_id=task.agent_id,
            role=Role.WORKER.value,
            model=task.model or "default",
            skills=", ".join(task.skills) if task.skills else "none",
            task=task.prompt,
            workspace=str(self.workspace.root),
        )

    def render_runtime_prompt(self, task: WorkerTask) -> str:
        return self.render_agents_md(task)

    def render_settings(self, task: WorkerTask) -> dict[str, Any]:
        return {
            "model": task.model,
            "skills": task.skills,
            "provider": task.provider.value,
            "mcp_servers": task.mcp_servers,
        }

    def render_permissions(self) -> dict[str, Any]:
        workspace_glob = f"{self.workspace.root}/*"
        return {
            "read": {workspace_glob: "allow"},
            "external_directory": {workspace_glob: "allow"},
        }

    def render_mcp_config(self, task: WorkerTask) -> dict[str, Any]:
        servers: dict[str, Any] = {}
        if "swarm" in task.mcp_servers:
            servers["swarm"] = {"command": "swarm-mcp"}
        if "octopoda" in task.mcp_servers:
            servers["octopoda"] = {
                "command": "python3",
                "args": ["-m", "synrix_runtime.api.mcp_server"],
            }
        return {"mcpServers": servers}

    def render_opencode_runtime_config(self, task: WorkerTask) -> dict[str, Any]:
        mcp_servers = self.render_mcp_config(task).get("mcpServers", {})
        opencode_mcp: dict[str, Any] = {}
        for name, config in mcp_servers.items():
            command = config.get("command")
            args = config.get("args", [])
            if isinstance(command, str):
                opencode_mcp[name] = {"type": "local", "command": [command, *args]}
        return {
            "mcp": opencode_mcp,
            "permission": self.render_permissions(),
        }

    def render_all(self, task: WorkerTask) -> RenderedWorkerConfig:
        self.workspace.ensure()
        agents_md_path = self.workspace.agent_file(task.agent_id)
        settings_path = self.workspace.settings_file(task.agent_id)
        permissions_path = self.workspace.permissions_file(task.agent_id)
        mcp_config_path = self.workspace.mcp_config_file(task.agent_id)

        agents_md_path.write_text(self.render_agents_md(task), encoding="utf-8")
        settings_path.write_text(
            json.dumps(self.render_settings(task), indent=2),
            encoding="utf-8",
        )
        permissions_path.write_text(
            json.dumps(self.render_permissions(), indent=2),
            encoding="utf-8",
        )
        mcp_config_path.write_text(
            json.dumps(self.render_mcp_config(task), indent=2),
            encoding="utf-8",
        )

        return RenderedWorkerConfig(
            agents_md_path=str(agents_md_path),
            settings_path=str(settings_path),
            permissions_path=str(permissions_path),
            mcp_config_path=str(mcp_config_path),
        )

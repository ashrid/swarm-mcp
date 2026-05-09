"""Provider command generation for worker spawns."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

from .config import SwarmConfig
from .types import ProviderKind, WorkerTask


@dataclass
class SpawnCommand:
    command: str
    env: dict[str, str]
    raw_command: str


class ProviderRouter:
    def __init__(self, config: SwarmConfig, workspace_root: str) -> None:
        self.config = config
        self.workspace_root = workspace_root

    def build(
        self,
        task: WorkerTask,
        *,
        prompt_text: str | None = None,
        opencode_config_content: str | None = None,
        generated_paths: dict[str, str] | None = None,
    ) -> SpawnCommand:
        provider = self.config.providers[task.provider]
        env = {
            "SWARM_ROLE": "worker",
            "SWARM_AGENT_ID": task.agent_id,
            "SWARM_WORKSPACE": self.workspace_root,
            "SWARM_TASK": task.prompt,
        }
        if generated_paths:
            for key, value in generated_paths.items():
                env[key] = value
        if task.provider == ProviderKind.OPENCODE:
            env["OPENCODE_PERMISSION"] = json.dumps(
                {"*": "allow", "read": "allow", "external_directory": "allow"}
            )
            if opencode_config_content is not None:
                env["OPENCODE_CONFIG_CONTENT"] = opencode_config_content

        effective_prompt = prompt_text or task.prompt

        parts = [provider.command, *provider.base_args]
        if task.provider == ProviderKind.OPENCODE and task.model:
            parts.extend(["--model", task.model])
        elif task.provider == ProviderKind.CLAUDE_CODE and task.model:
            parts.extend(["--model", task.model])

        if task.provider == ProviderKind.OPENCODE:
            parts.extend(["--prompt", effective_prompt])
        elif task.provider == ProviderKind.CLAUDE_CODE:
            parts.append(effective_prompt)
        elif task.provider == ProviderKind.CODEX:
            parts.extend(["--agent-id", task.agent_id, effective_prompt])

        raw_command = " ".join(shlex.quote(part) for part in parts)
        result_file = Path(self.workspace_root) / ".swarm" / "results" / f"{task.agent_id}.json"
        wrapper_parts = [
            "python3",
            "-m",
            "swarm_mcp.worker_runner",
            "--agent-id",
            task.agent_id,
            "--task-id",
            task.task_id,
            "--result-file",
            str(result_file),
            "--command",
            raw_command,
        ]
        command = " ".join(shlex.quote(part) for part in wrapper_parts)
        return SpawnCommand(command=command, env=env, raw_command=raw_command)

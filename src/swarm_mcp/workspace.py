"""Workspace and .swarm/ directory management."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path

from .types import WorkspacePaths


class WorkspaceManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.swarm_dir = self.root / ".swarm"

    @property
    def workspace_hash(self) -> str:
        return hashlib.md5(str(self.root).encode("utf-8"), usedforsecurity=False).hexdigest()[:6]

    @property
    def session_name(self) -> str:
        return f"swarm-{self.workspace_hash}"

    def paths(self) -> WorkspacePaths:
        return WorkspacePaths(
            root=str(self.root),
            swarm_dir=str(self.swarm_dir),
            session_name=self.session_name,
            config_path=str(self.swarm_dir / "config.yaml"),
            registry_path=str(self.swarm_dir / "registry.json"),
            heartbeat_path=str(self.swarm_dir / "heartbeat"),
        )

    def ensure(self) -> None:
        directories = [
            self.swarm_dir,
            self.swarm_dir / "agents",
            self.swarm_dir / "results",
            self.swarm_dir / "progress",
            self.swarm_dir / "thinking",
            self.swarm_dir / "messages",
            self.swarm_dir / "permissions",
            self.swarm_dir / "settings",
            self.swarm_dir / "snapshots",
            self.swarm_dir / "history",
            self.swarm_dir / "stats",
            self.swarm_dir / "costs",
            self.swarm_dir / "shared" / "artifacts",
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

        files = {
            self.swarm_dir / "main.lock": "",
            self.swarm_dir / "heartbeat": "",
            self.swarm_dir / "registry.json": json.dumps({"workers": []}, indent=2),
            self.swarm_dir / "agents.md.template": self.default_agents_template(),
        }
        for path, content in files.items():
            if not path.exists():
                path.write_text(content, encoding="utf-8")

    def default_agents_template(self) -> str:
        return (
            "## Swarm Protocol (Worker)\n\n"
            "> You are a WORKER. Execute the task fully and report RESULT when done.\n\n"
            "- agent_id: ${agent_id}\n"
            "- role: ${role}\n"
            "- model: ${model}\n"
            "- skills: ${skills}\n"
            "- task: ${task}\n"
            "- workspace: ${workspace}\n\n"
            "Every 30s, update progress. Check heartbeat periodically.\n"
        )

    def agent_file(self, agent_id: str) -> Path:
        return self.swarm_dir / "agents" / f"{agent_id}.md"

    def settings_file(self, agent_id: str) -> Path:
        return self.swarm_dir / "settings" / f"{agent_id}.json"

    def permissions_file(self, agent_id: str) -> Path:
        return self.swarm_dir / "permissions" / f"{agent_id}.json"

    def result_file(self, agent_id: str) -> Path:
        return self.swarm_dir / "results" / f"{agent_id}.json"

    def progress_file(self, agent_id: str) -> Path:
        return self.swarm_dir / "progress" / f"{agent_id}.json"

    def lock_file(self) -> Path:
        return self.swarm_dir / "main.lock"

    def write_main_lock(self, pid: int | None = None) -> None:
        payload = {
            "pid": pid if pid is not None else os.getpid(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workspace": str(self.root),
        }
        self.write_json(self.lock_file(), payload)

    def read_main_lock(self) -> dict[str, object] | None:
        path = self.lock_file()
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        if not text:
            return None
        payload = self.read_json(path, {})
        return payload if isinstance(payload, dict) else None

    def clear_main_lock(self) -> None:
        self.lock_file().write_text("", encoding="utf-8")

    def message_file(self, agent_id: str) -> Path:
        return self.swarm_dir / "messages" / f"{agent_id}.json"

    def mcp_config_file(self, agent_id: str) -> Path:
        return self.settings_file(agent_id).with_name(f"{agent_id}.mcp.json")

    def snapshot_file(self, agent_id: str) -> Path:
        return self.swarm_dir / "snapshots" / f"{agent_id}_pre.json"

    def write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def read_json(self, path: Path, default: object) -> object:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (JSONDecodeError, OSError, UnicodeDecodeError):
            return default

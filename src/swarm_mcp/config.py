"""Swarm configuration loading and defaults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from .types import JsonModel, ProviderConfig, ProviderKind


class BudgetConfig(JsonModel):
    default_task_budget: float = 5.0
    max_cost_per_provider: dict[str, float] = Field(
        default_factory=lambda: {"opencode": 50.0, "claude_code": 50.0, "codex": 50.0}
    )


class ThresholdConfig(JsonModel):
    heartbeat_interval_seconds: int = 30
    heartbeat_stale_seconds: int = 120
    stale_after_seconds: int = 120
    stale_kill_after_seconds: int = 300
    max_duration_default_seconds: int = 600
    dashboard_refresh_seconds: int = 5
    starvation_threshold_seconds: int = 600
    graceful_shutdown_seconds: int = 30
    max_turns_per_worker: int = 20


class PermissionMonitorConfig(JsonModel):
    denial_patterns: list[str] = Field(
        default_factory=lambda: [
            r"Denied\s+external_directory:\s+(?P<path>\S+)",
            r"Denied\s+read:\s+(?P<path>\S+)",
            r"To allow, add to opencode\.json",
        ]
    )


class SwarmConfig(JsonModel):
    workspace_root: str
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    permission_monitor: PermissionMonitorConfig = Field(default_factory=PermissionMonitorConfig)
    wiki_archive_dir: str | None = None
    providers: dict[ProviderKind, ProviderConfig]

    @classmethod
    def default(cls, workspace_root: str) -> "SwarmConfig":
        return cls(
            workspace_root=workspace_root,
            providers={
                ProviderKind.OPENCODE: ProviderConfig(
                    kind=ProviderKind.OPENCODE,
                    command="opencode",
                    base_args=["run", "--dangerously-skip-permissions", "--format", "json"],
                    default_model=None,
                    max_workers=5,
                ),
                ProviderKind.CLAUDE_CODE: ProviderConfig(
                    kind=ProviderKind.CLAUDE_CODE,
                    command="claude",
                    base_args=[
                        "-p",
                        "--dangerously-skip-permissions",
                        "--permission-mode",
                        "bypassPermissions",
                        "--output-format",
                        "json",
                    ],
                    default_model=None,
                    max_workers=3,
                ),
                ProviderKind.CODEX: ProviderConfig(
                    kind=ProviderKind.CODEX,
                    command="codex",
                    base_args=["--approval-policy", "never"],
                    default_model=None,
                    max_workers=3,
                ),
            },
        )

    @classmethod
    def load(cls, path: str | Path, workspace_root: str | None = None) -> "SwarmConfig":
        config_path = Path(path)
        if not config_path.exists():
            config = cls.default(workspace_root or str(config_path.parent.parent))
            config.save(config_path)
            return config

        text = config_path.read_text(encoding="utf-8")
        if config_path.suffix.lower() == ".json":
            data: dict[str, Any] = json.loads(text)
        else:
            data = yaml.safe_load(text) or {}
        return cls.model_validate(data)

    def save(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        if output_path.suffix.lower() == ".json":
            output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        else:
            output_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

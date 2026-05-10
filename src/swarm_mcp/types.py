"""Core typed models for swarm-mcp."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkerState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    STALE = "stale"
    DONE = "done"
    FAILED = "failed"


class Role(str, Enum):
    MAIN = "main"
    WORKER = "worker"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class FailureClass(str, Enum):
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    PROVIDER_ERROR = "provider_error"
    WORKER_CRASH = "worker_crash"
    STALE = "stale"
    TASK_TOO_COMPLEX = "task_too_complex"
    CONTEXT_OVERFLOW = "context_overflow"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNKNOWN = "unknown"


class ProviderKind(str, Enum):
    OPENCODE = "opencode"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class JsonModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(JsonModel):
    kind: ProviderKind
    command: str
    base_args: list[str] = Field(default_factory=list)
    default_model: str | None = None
    max_workers: int = 5
    cost_per_1k_input: float = Field(default=0.0, ge=0, le=1e6)
    cost_per_1k_output: float = Field(default=0.0, ge=0, le=1e6)

    @field_validator("cost_per_1k_input", "cost_per_1k_output", mode="before")
    @classmethod
    def _reject_bool_cost(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("cost rate must be a number, not a boolean")
        return v


class Heartbeat(JsonModel):
    agent_id: str
    role: Role
    timestamp: str = Field(default_factory=utc_now_iso)


class Progress(JsonModel):
    agent_id: str
    message: str = ""
    percent: float = 0.0
    updated_at: str = Field(default_factory=utc_now_iso)


class CostEntry(JsonModel):
    agent_id: str
    model: str
    provider: ProviderKind
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0)
    timestamp: str = Field(default_factory=utc_now_iso)


class Snapshot(JsonModel):
    snapshot_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    agent_id: str
    task_id: str
    before_state: dict[str, Any] = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)


class WorkerTask(JsonModel):
    task_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    agent_id: str
    provider: ProviderKind
    prompt: str
    model: str | None = None
    skills: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=lambda: ["swarm", "octopoda"])
    priority: Priority = Priority.NORMAL
    preemptible: bool = False
    budget_limit: float | None = None
    max_duration_seconds: int | None = None
    alert_after_seconds: int | None = None
    allow_peer_request: bool = False
    chain: list[dict[str, Any]] = Field(default_factory=list)
    on_done: str | None = None
    verify: bool = False
    prompt_overrides: dict[str, Any] = Field(default_factory=dict)
    max_lifetime_seconds: int = 600
    created_at: str = Field(default_factory=utc_now_iso)


class WorkerResult(JsonModel):
    task_id: str
    agent_id: str
    output: str
    exit_code: int = 0
    artifacts: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    failure_class: FailureClass | None = None
    cost: float = 0.0
    started_at: str = Field(default_factory=utc_now_iso)
    completed_at: str = Field(default_factory=utc_now_iso)


class WorkerStatus(JsonModel):
    agent_id: str
    task_id: str | None = None
    state: WorkerState = WorkerState.PENDING
    role: Role = Role.WORKER
    model: str | None = None
    provider: ProviderKind
    priority: Priority = Priority.NORMAL
    preemptible: bool = False
    budget_spent: float = 0.0
    started_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    pane_id: str | None = None
    session_name: str | None = None


class WorkspacePaths(JsonModel):
    root: str
    swarm_dir: str
    session_name: str
    config_path: str
    registry_path: str
    heartbeat_path: str


class RenderedWorkerConfig(JsonModel):
    agents_md_path: str
    settings_path: str
    permissions_path: str
    mcp_config_path: str


def json_dumpable_path(path: Path) -> str:
    return str(path)

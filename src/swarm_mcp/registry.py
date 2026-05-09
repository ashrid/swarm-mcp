"""Persistent worker registry for swarm state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .types import Role, WorkerStatus, WorkerTask
from .workspace import WorkspaceManager


@dataclass
class RegistryRecord:
    status: WorkerStatus
    task: WorkerTask | None = None


class WorkerRegistry:
    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace
        self._lock = asyncio.Lock()
        self._records: dict[str, RegistryRecord] = {}
        self._loaded = False

    async def load(self) -> None:
        async with self._lock:
            payload = self.workspace.read_json(
                self.workspace.swarm_dir / "registry.json",
                {"workers": []},
            )
            workers = payload.get("workers", []) if isinstance(payload, dict) else []
            self._records = {}
            for item in workers:
                status = WorkerStatus.model_validate(item["status"])
                task_data = item.get("task")
                task = WorkerTask.model_validate(task_data) if task_data else None
                self._records[status.agent_id] = RegistryRecord(status=status, task=task)
            self._loaded = True

    async def ensure_loaded(self) -> None:
        if not self._loaded:
            await self.load()

    async def save(self) -> None:
        async with self._lock:
            workers = [
                {
                    "status": record.status.model_dump(mode="json"),
                    "task": record.task.model_dump(mode="json") if record.task else None,
                }
                for record in self._records.values()
            ]
            self.workspace.write_json(
                self.workspace.swarm_dir / "registry.json",
                {"workers": workers},
            )

    async def register(self, status: WorkerStatus, task: WorkerTask | None = None) -> WorkerStatus:
        await self.ensure_loaded()
        if status.agent_id in self._records:
            raise ValueError(f"Worker already exists: {status.agent_id}")
        if status.role == Role.MAIN and any(
            record.status.role == Role.MAIN for record in self._records.values()
        ):
            raise ValueError("Main role already registered for this workspace")
        self._records[status.agent_id] = RegistryRecord(status=status, task=task)
        await self.save()
        return status

    async def update_status(self, agent_id: str, **changes: object) -> WorkerStatus:
        await self.ensure_loaded()
        if agent_id not in self._records:
            raise KeyError(f"Worker not found: {agent_id}")
        current = self._records[agent_id].status.model_copy(update=changes)
        self._records[agent_id].status = current
        await self.save()
        return current

    async def set_task(self, agent_id: str, task: WorkerTask) -> None:
        await self.ensure_loaded()
        if agent_id not in self._records:
            raise KeyError(f"Worker not found: {agent_id}")
        self._records[agent_id].task = task
        await self.save()

    async def get(self, agent_id: str) -> RegistryRecord:
        await self.ensure_loaded()
        if agent_id not in self._records:
            raise KeyError(f"Worker not found: {agent_id}")
        return self._records[agent_id]

    async def list(self) -> list[RegistryRecord]:
        await self.ensure_loaded()
        return list(self._records.values())

    async def remove(self, agent_id: str) -> None:
        await self.ensure_loaded()
        if agent_id not in self._records:
            raise KeyError(f"Worker not found: {agent_id}")
        del self._records[agent_id]
        await self.save()

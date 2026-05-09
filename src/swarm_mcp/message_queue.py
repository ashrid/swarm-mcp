"""Async task/result queue for swarm workers."""

from __future__ import annotations

import asyncio

from .types import WorkerResult, WorkerTask


class MessageQueue:
    def __init__(self) -> None:
        self._tasks: dict[str, WorkerTask] = {}
        self._results: dict[str, asyncio.Queue[WorkerResult]] = {}

    def publish_task(self, task: WorkerTask) -> None:
        self._tasks[task.agent_id] = task
        self._results.setdefault(task.agent_id, asyncio.Queue())

    def peek_task(self, agent_id: str) -> WorkerTask | None:
        return self._tasks.get(agent_id)

    async def submit_result(self, result: WorkerResult) -> None:
        queue = self._results.setdefault(result.agent_id, asyncio.Queue())
        await queue.put(result)

    async def collect_result(self, agent_id: str, timeout: float | None = None) -> WorkerResult:
        if agent_id not in self._results:
            self._results[agent_id] = asyncio.Queue()
        if timeout is None:
            return await self._results[agent_id].get()
        return await asyncio.wait_for(self._results[agent_id].get(), timeout=timeout)

"""History, snapshots, and cost tracking helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import CostEntry, Snapshot, WorkerStatus, WorkerTask
from .workspace import WorkspaceManager


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HistoryTracker:
    workspace: WorkspaceManager

    def log_event(self, event_type: str, payload: dict[str, Any]) -> Path:
        history_dir = (
            self.workspace.swarm_dir
            / "history"
            / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        history_dir.mkdir(parents=True, exist_ok=True)
        timeline = history_dir / "timeline.jsonl"
        entry = {"timestamp": _utc_now_iso(), "event": event_type, "payload": payload}
        with timeline.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return timeline

    def read_timeline(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in sorted((self.workspace.swarm_dir / "history").glob("*/timeline.jsonl")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line in text.splitlines():
                if line.strip():
                    try:
                        item = json.loads(line)
                        if isinstance(item, dict):
                            entries.append(item)
                    except json.JSONDecodeError:
                        continue
        return entries


@dataclass
class SnapshotManager:
    workspace: WorkspaceManager

    def create(self, status: WorkerStatus, task: WorkerTask | None = None) -> Snapshot:
        snapshot = Snapshot(
            agent_id=status.agent_id,
            task_id=status.task_id or (task.task_id if task else "unknown"),
            before_state={
                "status": status.model_dump(mode="json"),
                "task": task.model_dump(mode="json") if task else None,
            },
            files=[],
        )
        self.workspace.write_json(
            self.workspace.snapshot_file(status.agent_id),
            snapshot.model_dump(mode="json"),
        )
        return snapshot

    def read(self, agent_id: str) -> Snapshot | None:
        path = self.workspace.snapshot_file(agent_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Snapshot.model_validate(data)
        except (json.JSONDecodeError, OSError, Exception):
            return None


@dataclass
class CostTracker:
    workspace: WorkspaceManager

    def _costs_path(self) -> Path:
        return self.workspace.swarm_dir / "costs" / "current.json"

    def add(self, entry: CostEntry) -> None:
        payload = self.workspace.read_json(self._costs_path(), {"entries": []})
        if not isinstance(payload, dict):
            payload = {"entries": []}
        raw_entries: Any = payload.get("entries", [])
        entries: list[dict[str, Any]] = raw_entries if isinstance(raw_entries, list) else []
        entries.append(entry.model_dump(mode="json"))
        self.workspace.write_json(self._costs_path(), {"entries": entries})

    def summary(self) -> dict[str, Any]:
        import math

        payload = self.workspace.read_json(self._costs_path(), {"entries": []})
        if not isinstance(payload, dict):
            payload = {"entries": []}
        raw_entries: list[Any] = payload.get("entries", [])
        if not isinstance(raw_entries, list):
            raw_entries = []
        entries: list[CostEntry] = []
        for item in raw_entries:
            try:
                if isinstance(item, dict) and (
                    isinstance(item.get("estimated_cost"), bool)
                    or isinstance(item.get("input_tokens"), bool)
                    or isinstance(item.get("output_tokens"), bool)
                ):
                    continue
                entry = CostEntry.model_validate(item)
                if math.isfinite(entry.estimated_cost) and entry.estimated_cost >= 0:
                    entries.append(entry)
            except Exception:
                continue
        total_cost = sum(entry.estimated_cost for entry in entries)
        by_provider: dict[str, float] = {}
        for entry in entries:
            by_provider.setdefault(entry.provider.value, 0.0)
            by_provider[entry.provider.value] += entry.estimated_cost
        return {
            "total_cost": total_cost,
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "by_provider": by_provider,
        }

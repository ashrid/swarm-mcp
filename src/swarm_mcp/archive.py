"""Archive swarm sessions to markdown and purge transient files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import WorkspaceManager


@dataclass
class ArchiveManager:
    workspace: WorkspaceManager
    wiki_archive_dir: str | None = None

    def _results(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in sorted((self.workspace.swarm_dir / "results").glob("*.json")):
            results.append(json.loads(path.read_text(encoding="utf-8")))
        return results

    def _history(self) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for path in sorted((self.workspace.swarm_dir / "history").glob("*/timeline.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    history.append(json.loads(line))
        return history

    def build_session_markdown(self) -> str:
        created = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [
            f"# Swarm Session Archive — {self.workspace.root.name}",
            "",
            f"- Generated: {created}",
            f"- Workspace: `{self.workspace.root}`",
            "",
            "## Results",
        ]
        results = self._results()
        if not results:
            lines.append("- No results persisted yet.")
        for result in results:
            lines.extend(
                [
                    f"### {result.get('agent_id', 'unknown')}",
                    f"- Task ID: `{result.get('task_id', 'unknown')}`",
                    f"- Confidence: `{result.get('confidence', 0.0)}`",
                    "- Output:",
                    "```text",
                    str(result.get("output", "")),
                    "```",
                    "",
                ]
            )
        lines.append("## Chronological Timeline")
        for event in self._history():
            lines.append(
                f"- {event.get('timestamp')} — **{event.get('event')}** — "
                f"`{event.get('payload')}`"
            )
        return "\n".join(lines) + "\n"

    def archive_to_markdown(self) -> Path | None:
        if not self.wiki_archive_dir:
            return None
        archive_root = Path(self.wiki_archive_dir)
        archive_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        file_name = f"{self.workspace.root.name}-session-{timestamp}.md"
        output_path = archive_root / file_name
        output_path.write_text(self.build_session_markdown(), encoding="utf-8")
        return output_path

    def cleanup_transient_files(self) -> dict[str, int]:
        removed = 0
        for folder_name in ["results", "progress", "thinking", "messages"]:
            folder = self.workspace.swarm_dir / folder_name
            for path in folder.glob("*"):
                path.unlink(missing_ok=True)
                removed += 1
        return {"removed_files": removed}

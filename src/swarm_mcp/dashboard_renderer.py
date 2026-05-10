"""Standalone dashboard renderer for a live tmux pane."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError, TypeError, UnicodeDecodeError):
        return {}


def render_dashboard(swarm_dir: Path) -> str:
    registry_path = swarm_dir / "registry.json"
    costs_path = swarm_dir / "costs" / "current.json"
    registry_data = _load_json(registry_path)
    costs_data = _load_json(costs_path)

    workers = registry_data.get("workers", [])
    if not isinstance(workers, list):
        workers = []

    queue_depth: dict[str, int] = {}
    lines = ["SWARM DASHBOARD", "=" * 40, f"Workers: {len(workers)}"]

    if not workers:
        lines.append("  - none")
    for worker in workers:
        status = worker.get("status", worker) if isinstance(worker, dict) else {}
        if not isinstance(status, dict):
            status = {}
        state = str(status.get("state", "unknown"))
        provider = str(status.get("provider", "unknown"))
        model = str(status.get("model") or "default")
        priority = str(status.get("priority", "normal"))
        agent_id = str(status.get("agent_id", "unknown"))
        line = f"  - {agent_id} | {state} | {provider} | {model} | {priority}"
        lines.append(line)
        if state == "pending":
            queue_depth[provider] = queue_depth.get(provider, 0) + 1

    lines.append("")
    lines.append("Queue depth by provider:")
    if not queue_depth:
        lines.append("  - empty")
    for provider, depth in sorted(queue_depth.items()):
        lines.append(f"  - {provider}: {depth}")

    def _safe_float(value: Any) -> float | None:
        import math

        try:
            if isinstance(value, bool):
                return None
            result = float(value)
            if not math.isfinite(result) or result < 0:
                return None
            return result
        except (ValueError, TypeError):
            return None

    entries = costs_data.get("entries", [])
    if isinstance(entries, list) and entries:
        valid_costs = [
            cost
            for e in entries
            if isinstance(e, dict)
            for cost in (_safe_float(e.get("estimated_cost")),)
            if cost is not None
        ]
        if valid_costs:
            total_cost = sum(valid_costs)
            lines.append("")
            lines.append(f"Total cost: ${total_cost:.4f}")

    lines.append("")
    lines.append(f"Updated: {time.strftime('%H:%M:%S')}")
    return "\n".join(lines)


def main() -> None:
    swarm_dir = Path.cwd() / ".swarm"
    if len(sys.argv) > 1:
        swarm_dir = Path(sys.argv[1])

    refresh_interval = float(os.environ.get("SWARM_DASHBOARD_REFRESH", "5"))

    while True:
        output = render_dashboard(swarm_dir)
        os.system("clear")
        print(output, flush=True)
        time.sleep(refresh_interval)


if __name__ == "__main__":
    main()

"""Dashboard, stats, and report helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .planner import classify_task_category
from .tracking import CostTracker, HistoryTracker


@dataclass
class ReportingService:
    history: HistoryTracker
    costs: CostTracker

    def stats(self) -> dict[str, Any]:
        events = self.history.read_timeline()
        spawn_count = sum(1 for event in events if event.get("event") == "swarm_spawn")
        retry_count = sum(1 for event in events if event.get("event") == "swarm_retry")
        send_count = sum(1 for event in events if event.get("event") == "swarm_send")
        spawns_by_agent: dict[str, dict[str, Any]] = {}
        successes_by_model: dict[str, int] = {}
        failures_by_model: dict[str, int] = {}
        successes_by_provider: dict[str, int] = {}
        failures_by_provider: dict[str, int] = {}
        successes_by_category_and_model: dict[str, dict[str, int]] = {}
        failures_by_category_and_model: dict[str, dict[str, int]] = {}

        for event in events:
            event_type = event.get("event")
            payload = event.get("payload", {})
            if event_type == "swarm_spawn":
                agent_id = payload.get("agent_id")
                if isinstance(agent_id, str):
                    spawns_by_agent[agent_id] = payload
            elif event_type == "swarm_collect":
                agent_id = payload.get("agent_id")
                spawn = spawns_by_agent.get(agent_id, {}) if isinstance(agent_id, str) else {}
                model = str(spawn.get("model") or "default")
                provider = str(spawn.get("provider") or "unknown")
                category = classify_task_category(str(spawn.get("task") or ""))
                successes_by_model[model] = successes_by_model.get(model, 0) + 1
                successes_by_provider[provider] = successes_by_provider.get(provider, 0) + 1
                successes_by_category_and_model.setdefault(category, {})
                successes_by_category_and_model[category][model] = (
                    successes_by_category_and_model[category].get(model, 0) + 1
                )
            elif event_type == "swarm_terminate":
                model = str(payload.get("model") or "default")
                provider = str(payload.get("provider") or "unknown")
                category = classify_task_category(str(payload.get("task") or ""))
                failures_by_model[model] = failures_by_model.get(model, 0) + 1
                failures_by_provider[provider] = failures_by_provider.get(provider, 0) + 1
                failures_by_category_and_model.setdefault(category, {})
                failures_by_category_and_model[category][model] = (
                    failures_by_category_and_model[category].get(model, 0) + 1
                )

        cost_summary = self.costs.summary()
        return {
            "spawn_count": spawn_count,
            "retry_count": retry_count,
            "send_count": send_count,
            "total_cost": cost_summary["total_cost"],
            "by_provider": cost_summary["by_provider"],
            "successes_by_model": successes_by_model,
            "failures_by_model": failures_by_model,
            "successes_by_provider": successes_by_provider,
            "failures_by_provider": failures_by_provider,
            "successes_by_category_and_model": successes_by_category_and_model,
            "failures_by_category_and_model": failures_by_category_and_model,
        }

    def recommend_model(self, task: str, fallback: str | None = None) -> str | None:
        stats = self.stats()
        category = classify_task_category(task)
        category_successes = stats["successes_by_category_and_model"].get(category, {})
        category_failures = stats["failures_by_category_and_model"].get(category, {})
        candidates = set(category_successes) | set(category_failures)
        if not candidates:
            return fallback

        def score(model: str) -> tuple[int, int]:
            successes = int(category_successes.get(model, 0))
            failures = int(category_failures.get(model, 0))
            return (successes - failures, successes)

        return str(max(sorted(candidates), key=score))

    def report(self) -> dict[str, Any]:
        stats = self.stats()
        recommendations: list[str] = []
        if stats["retry_count"] > 0:
            recommendations.append("Review repeated retries and consider provider/model overrides.")
        if stats["spawn_count"] and stats["total_cost"] == 0:
            recommendations.append("Add real token/cost ingestion once provider outputs are wired.")
        if stats["failures_by_model"]:
            worst_model = max(
                stats["failures_by_model"],
                key=lambda name: stats["failures_by_model"][name],
            )
            recommendations.append(
                f"Highest observed failure count so far: {worst_model} "
                f"({stats['failures_by_model'][worst_model]} failures)."
            )
        if stats["successes_by_model"]:
            best_model = max(
                stats["successes_by_model"],
                key=lambda name: stats["successes_by_model"][name],
            )
            recommendations.append(
                f"Best observed completion count so far: {best_model} "
                f"({stats['successes_by_model'][best_model]} successes)."
            )
        category_models = stats["successes_by_category_and_model"]
        for category, models in category_models.items():
            if not models:
                continue
            best_for_category = max(models, key=models.get)
            recommendations.append(
                f"Best observed model for {category} tasks so far: {best_for_category} "
                f"({models[best_for_category]} successes)."
            )
        if not recommendations:
            recommendations.append("Swarm activity looks stable so far.")
        return {"stats": stats, "recommendations": recommendations}

    def render_dashboard_text(
        self,
        workers: list[dict[str, Any]],
        queue_depth_by_provider: dict[str, int],
    ) -> str:
        stats = self.stats()
        lines = [
            "SWARM DASHBOARD",
            "===============",
            f"Workers: {len(workers)}",
            (
                f"Spawned: {stats['spawn_count']}  Retries: {stats['retry_count']}  "
                f"Sends: {stats['send_count']}"
            ),
            f"Total cost: ${stats['total_cost']:.2f}",
            "",
            "Workers:",
        ]
        if not workers:
            lines.append("  - none")
        for worker in workers:
            lines.append(
                (
                    "  - {agent_id} | {state} | {provider} | model={model} | "
                    "priority={priority} | alive={alive}"
                ).format(
                    agent_id=worker.get("agent_id", "unknown"),
                    state=worker.get("state", "unknown"),
                    provider=worker.get("provider", "unknown"),
                    model=worker.get("model") or "default",
                    priority=worker.get("priority", "normal"),
                    alive=worker.get("alive", False),
                )
            )
        lines.append("")
        lines.append("Queue depth by provider:")
        if not queue_depth_by_provider:
            lines.append("  - empty")
        for provider, depth in sorted(queue_depth_by_provider.items()):
            lines.append(f"  - {provider}: {depth}")
        return "\n".join(lines)

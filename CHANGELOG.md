# Changelog

## 0.1.0

- Initial working `swarm-mcp` package scaffold with FastMCP stdio server
- Workspace-backed `.swarm/` state model and AGENTS/config generation
- Core orchestration tools for spawn, status, terminate, send, collect, replay, waits, retry, permission requests, decompose/execute, workflow, shutdown, dashboard, costs, stats, report, cleanup, undo/rollback, and claim-main
- `worker_runner` wrapper for real provider command execution and persisted result files
- Background stale monitor with thinking capture and queue dispatch
- Cost tracking, archive generation, textual dashboard rendering, performance recommendation heuristics
- Verified baseline with pytest, mypy, ruff, startup probe, and runnable example

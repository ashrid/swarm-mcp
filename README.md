# swarm-mcp

Semi-autonomous swarm orchestration MCP server for OpenCode, Claude Code, and Codex.

## What exists right now

This repository already includes a working foundation and a substantial portion of the orchestration surface:

- FastMCP stdio server scaffold
- Workspace-backed `.swarm/` state directory creation
- Persistent worker registry
- In-memory task/result queue
- Provider-aware worker command generation
- Per-worker AGENTS/settings/permission/MCP config generation
- Core tools: `swarm_init`, `swarm_spawn`, `swarm_status`, `swarm_terminate`, `swarm_send`, `swarm_collect`, `swarm_results`, `swarm_wait_any`, `swarm_wait_all`, `swarm_retry`, `swarm_ask_permission`, `swarm_decompose`, `swarm_execute`, `swarm_shutdown`, `swarm_broadcast`, `swarm_request_peer`, `swarm_health`, `swarm_costs`, `swarm_stats`, `swarm_report`, `swarm_history`, `swarm_undo`, `swarm_rollback`, `swarm_dashboard`, `swarm_cleanup`, `swarm_workflow`
- History, snapshots, and basic cost tracking
- Markdown archival for completed swarm sessions

## Current tool surface

| Tool | Status | Notes |
|------|--------|-------|
| `swarm_init` | implemented | Creates `.swarm/` structure and default config |
| `swarm_spawn` | implemented | Supports model/skills/MCP/priority/budget params |
| `swarm_status` | implemented | Includes progress file if present |
| `swarm_terminate` | implemented | Marks worker failed and attempts queued dispatch |
| `swarm_send` | implemented | Writes message file + tmux inject |
| `swarm_collect` | implemented | Collects queued result or replay from disk |
| `swarm_results` | implemented | Replays all persisted result files |
| `swarm_wait_any` / `swarm_wait_all` | implemented | File-backed wait logic |
| `swarm_retry` | implemented | Respawns from original task |
| `swarm_ask_permission` | implemented | Pending/allow/deny file-backed requests |
| `swarm_decompose` / `swarm_execute` | implemented | Lightweight decomposition + spawn loop |
| `swarm_broadcast` | implemented | Fan-out by provider |
| `swarm_request_peer` | implemented | Peer spawn when explicitly allowed |
| `swarm_shutdown` | implemented | Graceful or immediate |
| `swarm_health` | implemented | Live worker summary |
| `swarm_costs` / `swarm_record_cost` | implemented | Cost tracking + task-budget gate |
| `swarm_stats` / `swarm_report` | implemented | Historical performance + recommendations |
| `swarm_history` | implemented | Timeline replay |
| `swarm_undo` / `swarm_rollback` | implemented | Snapshot/timeline readback |
| `swarm_dashboard` | implemented | JSON + human-readable text dashboard |
| `swarm_cleanup` | implemented | Archive markdown + purge transient files |
| `swarm_workflow` | implemented | Named workflow planning/execution wrapper |
| `swarm_claim_main` | implemented | Main lock takeover |

## Install

```bash
python3 -m pip install -e .[dev]
```

## Run

```bash
python3 -m swarm_mcp
```

The server runs over stdio using FastMCP.

## Quick dev checks

```bash
python3 -m pytest tests -q
python3 -m mypy src tests
python3 -m ruff check src tests
timeout 3s python3 -m swarm_mcp
```

## Workspace model

The server treats the current working directory as the swarm workspace. On first initialization it creates:

```text
.swarm/
├── agents/
├── results/
├── progress/
├── thinking/
├── messages/
├── permissions/
├── settings/
├── snapshots/
├── history/
├── stats/
├── costs/
└── shared/artifacts/
```

## Example flow

1. Start the server:

   ```bash
   python3 -m swarm_mcp
   ```

2. Initialize the workspace:

   - Call `swarm_init()` from your MCP client.

3. Spawn a worker:

   - `swarm_spawn(agent_id="worker-1", provider="opencode", task="analyze auth module")`

   Advanced variants:

   - `swarm_spawn(agent_id="worker-2", provider="opencode", task="refactor auth service", model="auto")`
   - `swarm_spawn(agent_id="worker-3", provider="claude_code", task="debug login loop", skills=["gsd-debug"], budget_limit=2.0)`
   - `swarm_spawn(agent_id="worker-4", provider="opencode", task="security audit", priority="critical", preemptible=false)`

4. Inspect progress:

   - `swarm_status()`
   - `swarm_dashboard()`

5. Collect or replay results:

   - `swarm_collect(agent_id="worker-1")`
   - `swarm_results()`

6. Archive and clean up:

   - `swarm_cleanup(force=True)`

## How worker execution works today

Workers are launched through a wrapper process:

```text
swarm_spawn
  -> ProviderRouter builds underlying provider command
  -> worker_runner executes that provider command
  -> stdout is mirrored to tmux and captured into .swarm/results/{agent_id}.json
  -> swarm_collect / swarm_results read the persisted result file
```

This means the current system has a real spawn → result path, not just an in-memory queue placeholder.

## Queueing and caps

- Provider concurrency caps are enforced at spawn time.
- If a provider is full, the task is persisted as `PENDING` and returned as `queued`.
- `swarm_dispatch_queue()` launches queued work when slots free up.
- `swarm_dashboard()` exposes queue depth by provider.

## Archive configuration

If you want `swarm_cleanup()` to write session markdown before purging, set `wiki_archive_dir` in `.swarm/config.yaml`:

```yaml
wiki_archive_dir: /mnt/c/Users/force/obsidian-wiki-vault/projects/swarm
```

When configured, cleanup writes a per-session markdown archive and then removes transient files.

## Example script

See [`examples/basic_swarm.py`](examples/basic_swarm.py) for a local Python example that exercises the workspace, registry, router, and renderer directly.

## Current scope and hardening opportunities

This repository now has a working, verified implementation slice. The remaining items below are hardening opportunities and deeper autonomy features, not blockers for exercising the current system locally:

- `model="auto"` uses local history heuristics, not a rich evaluation engine yet
- No true live tmux dashboard pane renderer loop yet (dashboard text is ready)
- No full semantic task similarity engine yet (only exact normalized-task blocking)
- No provider-native token/cost ingestion yet; cost recording is explicit via `swarm_record_cost`
- Worker execution loop is represented through file-backed orchestration and current tooling, not a fully closed autonomous loop controller yet
- Permission escalation is file-backed and reviewable, but not yet tied to a full non-interactive provider denial parser pipeline
- Trusted workflows are present as named wrappers, not a mature workflow registry yet

## Project structure

```text
src/swarm_mcp/
├── __init__.py
├── __main__.py
├── archive.py
├── config.py
├── logging.py
├── message_queue.py
├── planner.py
├── provider_router.py
├── registry.py
├── reporting.py
├── server.py
├── templates.py
├── tmux_manager.py
├── tracking.py
├── types.py
└── workspace.py
```

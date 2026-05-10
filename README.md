# Swarm MCP

**Semi-autonomous swarm orchestration MCP server.** Run multiple AI sessions as a coordinated team — one Main Brain directs strategy while workers execute in parallel tmux panes. Works with OpenCode, Claude Code, and Codex.

[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-69%2F69-brightgreen)](tests/)
[![Type Check](https://img.shields.io/badge/mypy-strict-brightgreen)](https://mypy-lang.org)
[![Lint](https://img.shields.io/badge/ruff-clean-brightgreen)](https://docs.astral.sh/ruff)

---

## What is Swarm MCP?

Swarm MCP is an MCP (Model Context Protocol) server that turns your AI CLI into a multi-agent orchestrator. Instead of running one session at a time, you run a **Main Brain** that spawns, monitors, and coordinates **worker sessions** — each in its own tmux pane, each with its own model, skills, and task.

```
┌────────────────────┬──────────────────┐
│                    │  [W] worker-1    │
│   [M] MAIN BRAIN   │  (kimi-coding)   │
│   (reasoning)       ├──────────────────┤
│                    │  [W] worker-2    │
│   - decomposes     │  (claude-sonnet) │
│   - approves       ├──────────────────┤
│   - monitors       │  [W] worker-3    │
│   - decides        │  (deepseek)      │
│                    ├──────────────────┤
│                    │  SWARM DASHBOARD │
│                    │  [auto-refresh]  │
└────────────────────┴──────────────────┘
```

### Key features

- **33 MCP tools** — spawn, monitor, wait, retry, collect, broadcast, decompose, archive, rollback
- **Multi-provider** — workers can run on different AI CLIs and models simultaneously
- **Semi-autonomous** — the server handles routine ops; you handle strategy and exceptions
- **Cost tracking** — per-task budgets, provider caps, running cost totals
- **Crash recovery** — heartbeat TTL, stale detection, `swarm_claim_main` takeover
- **Snapshot/rollback** — undo individual workers or rewind the entire swarm
- **Wiki archival** — auto-generate session summaries on cleanup
- **Mock mode** — test without tmux installed

---

## Prerequisites

| Requirement | Minimum | Check |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| pip | latest | `python3 -m pip --version` |
| tmux | 3.0+ | `tmux -V` |
| git | any | `git --version` |

> **tmux is optional** for testing. The mock mode lets you validate behavior without tmux. Real worker execution requires tmux.

---

## Installation

### Step 1 — Clone

```bash
git clone https://github.com/your-username/swarm-mcp.git
cd swarm-mcp
```

### Step 2 — Install dependencies

```bash
python3 -m pip install -e ".[dev]"
```

This installs:

| Package | Purpose |
|---|---|
| `mcp>=1.0.0` | FastMCP server framework (stdio transport) |
| `libtmux>=0.55` | Tmux session management |
| `pydantic>=2.8` | Type validation and config models |
| `PyYAML>=6.0` | Configuration file parsing |
| `pytest>=8.0` | Test runner _(dev)_ |
| `mypy>=1.10` | Static type checker _(dev)_ |
| `ruff>=0.6` | Linter _(dev)_ |

### Step 3 — Verify

```bash
python3 -m pytest tests -q       # 69 tests, all passing
python3 -m mypy src              # zero type errors
python3 -m ruff check src        # zero lint issues
timeout 3s python3 -m swarm_mcp  # server boots successfully
```

All four should pass before proceeding.

---

## Client Configuration

Add Swarm MCP to your AI client's MCP server list. The configuration is the same across all clients — only the file path differs.

### OpenCode

Add to `~/.openclaw/mcp.json` or `mcp.json` in your project root:

```json
{
  "mcpServers": {
    "swarm": {
      "command": "python3",
      "args": ["-m", "swarm_mcp"],
      "cwd": "/path/to/swarm-mcp"
    }
  }
}
```

### Claude Code

Add to `~/.claude/mcp.json` or `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "swarm": {
      "command": "python3",
      "args": ["-m", "swarm_mcp"],
      "cwd": "/path/to/swarm-mcp"
    }
  }
}
```

### Codex (OpenAI Codex CLI)

Add to your Codex MCP configuration file:

```json
{
  "mcpServers": {
    "swarm": {
      "command": "python3",
      "args": ["-m", "swarm_mcp"],
      "cwd": "/path/to/swarm-mcp"
    }
  }
}
```

### Other MCP-compatible clients

Swarm MCP uses standard stdio MCP transport. Any client that supports the MCP protocol can connect — the server is provider-agnostic. This includes:

- **Gemini CLI** — Google's AI CLI with MCP support
- **Cursor** — AI code editor with MCP integration
- **Continue** — open-source AI code assistant
- **Any stdio MCP client** — the server speaks standard JSON-RPC over stdin/stdout

Configuration is identical: point `command` to `python3 -m swarm_mcp` with the correct `cwd`.

> **Restart your client** after adding the MCP config for the tools to appear.

---

## Quick Start

Once the server is configured in your client, restart the client and follow this flow:

### 1. Initialize the workspace

```
swarm_init()
```

Creates a `.swarm/` directory in your current working directory with all required subdirectories and a default config.

### 2. Spawn workers

```
swarm_spawn(agent_id="worker-1", provider="opencode", task="audit auth module for vulnerabilities")
swarm_spawn(agent_id="worker-2", provider="claude_code", task="review database schema for normalization issues")
swarm_spawn(agent_id="worker-3", provider="opencode", task="check dependency versions for CVEs")
```

Each worker gets its own tmux pane, AGENTS.md, settings, and permissions config. Workers run in parallel up to the provider concurrency cap.

Advanced spawn options:

```
swarm_spawn(
    agent_id="worker-4",
    provider="opencode",
    task="refactor payment service",
    model="auto",                    # model="auto" picks the best model based on history
    skills=["gsd-debug"],            # load specific skills
    budget_limit=2.0,                # main-side enforcement when cost reaches or exceeds $2
    priority="critical",             # stored for reference (queue ordering not yet implemented)
    preemptible=False,               # stored for reference (preemption not yet implemented)
    max_lifetime=600,                # stored for retry/reference (not yet enforced)
)
```

### 3. Monitor progress

```
swarm_status()       # list all workers with state, model, progress
swarm_dashboard()    # full swarm overview in one call
swarm_health()       # stale worker detection and health summary
```

### 4. Wait and collect

```
swarm_wait_all()                              # block until all workers finish
swarm_collect(agent_id="worker-1")             # get a specific worker's result
swarm_results()                                # replay all persisted results
```

### 5. Clean up

```
swarm_cleanup(force=True)    # archive session to markdown + purge transient files
```

---

## Tool Reference

### Lifecycle

| Tool | Description |
|---|---|
| `swarm_init()` | Bootstrap `.swarm/` directory and default config |
| `swarm_spawn(agent_id, provider, task, ...)` | Create a worker in a tmux pane |
| `swarm_terminate(agent_id)` | Kill a worker and cleanup |
| `swarm_retry(agent_id, ...)` | Re-spawn with smart failure analysis |
| `swarm_broadcast(task, providers=None)` | Fan-out the same task to N workers |
| `swarm_shutdown(graceful=True)` | Graceful or immediate shutdown |

### Communication

| Tool | Description |
|---|---|
| `swarm_send(agent_id, message)` | Send mid-flight message to a worker |
| `swarm_collect(agent_id)` | Get result from a finished worker |

### Monitoring

| Tool | Description |
|---|---|
| `swarm_status(agent_id?)` | Worker status, model, progress, cost |
| `swarm_dashboard()` | Full swarm state in one call |
| `swarm_dashboard_pane()` | Live tmux dashboard pane |
| `swarm_health()` | Stale detection and health summary |

### Wait & Results

| Tool | Description |
|---|---|
| `swarm_wait_any()` | Block until first worker finishes |
| `swarm_wait_all()` | Block until all workers finish |
| `swarm_results()` | Replay all persisted results from disk |

### Planning & Execution

| Tool | Description |
|---|---|
| `swarm_decompose(task)` | Auto-split complex task into sub-tasks |
| `swarm_execute(plan_name, subtasks, provider)` | Spawn all workers from an approved plan |
| `swarm_workflow(name, autonomous=False)` | Named workflow planning/execution wrapper |

### Analysis

| Tool | Description |
|---|---|
| `swarm_stats()` | Historical performance per model and task category |
| `swarm_report()` | Performance report with model recommendations |
| `swarm_costs()` | Running cost totals and budget status |
| `swarm_record_cost(agent_id, amount, input_tokens, output_tokens)` | Manually record a cost entry |

### Recovery

| Tool | Description |
|---|---|
| `swarm_history()` | Full execution timeline |
| `swarm_undo(agent_id)` | Rollback a single worker via pre-execution snapshot |
| `swarm_rollback(to_step)` | Rewind entire swarm to a specific step |
| `swarm_claim_main()` | Take over MAIN role from a dead session |

### Self-Service

| Tool | Description |
|---|---|
| `swarm_whoami()` | Self-identification (role, workspace) |
| `swarm_ask_permission(agent_id, path, reason, action)` | Worker requests file access; Main approves/denies |
| `swarm_request_peer(agent_id, task)` | Worker requests a peer for a sub-task |
| `swarm_cleanup(force=False)` | Manual archival and purge trigger |

---

## How It Works

```
swarm_spawn(agent_id="worker-1", provider="opencode", task="...")
  │
  ├─ 1. ProviderRouter builds the provider CLI command
  │     (opencode → opencode run --prompt "...", claude_code → claude ...)
  │
  ├─ 2. Templates render per-worker config files:
  │     AGENTS.md, settings.local.json, permissions.json, mcp.json
  │
  ├─ 3. worker_runner launches the provider command in tmux
  │     stdout → mirrored to tmux pane + written to .swarm/results/{agent_id}.json
  │
  ├─ 4. Background monitor tracks progress, heartbeat, staleness
  │
  └─ 5. swarm_collect / swarm_results reads the persisted result file
```

### Concurrency model

- Each provider has a configurable concurrency cap (default: 5 for OpenCode, 3 for Claude Code, 3 for Codex)
- Workers exceeding the cap are queued as `PENDING`
- `swarm_dispatch_queue()` auto-launches queued workers when slots free up
- `swarm_dashboard()` exposes queue depth by provider

### Failure handling

| Scenario | Detection | Recovery |
|---|---|---|
| Worker stale (rate limited) | Output frozen + pattern match | Smart retry suggests provider switch |
| Worker exceeds `max_lifetime` | Not monitored | Stored for reference only |
| Worker starved in queue | Queue time > threshold | Notify Main (priority bump not yet implemented) |
| Main Brain crashes | Heartbeat stale | Workers self-terminate via TTL |
| Two Main sessions | Lock file collision | Second MAIN warned, runs standalone |
| Duplicate task | Normalized text match | Block if active or similar task running |
| Budget exceeded | Cost counter >= `budget_limit` | Main-side kill on next cost record |

---

## Workspace Layout

```
.swarm/
├── main.lock              # split-brain prevention
├── heartbeat               # Main Brain liveness
├── registry.json           # all worker state
├── config.yaml             # thresholds, budgets, provider caps
├── agents.md.template      # AGENTS.md template for workers
├── agents/                 # generated AGENTS.md per worker
├── results/                # persisted worker results
├── progress/               # worker self-reported progress
├── thinking/               # verbose output captured on stale detection
├── messages/               # swarm_send messages
├── permissions/            # per-worker path allow lists
├── settings/               # generated settings.local.json per worker
├── snapshots/              # pre-execution state for undo/rollback
├── history/                # full execution timelines
├── stats/                  # performance data per model/task
├── costs/                  # running cost totals
└── shared/artifacts/       # inter-worker large data exchange
```

---

## Development

```bash
# Install with dev dependencies
python3 -m pip install -e ".[dev]"

# Run tests
python3 -m pytest tests -v

# Type check (strict mode)
python3 -m mypy src

# Lint
python3 -m ruff check src

# Run example script (no tmux needed)
python3 examples/basic_swarm.py
```

### Running with mock tmux

Tests use a mock tmux manager. To validate end-to-end behavior without a real tmux installation:

```bash
python3 -m pytest tests/ -v
```

All 69 tests pass in mock mode. Real tmux integration requires `tmux` installed on the system.

---

## Project Structure

```
src/swarm_mcp/
├── __init__.py           # package init
├── __main__.py           # entry point (python3 -m swarm_mcp)
├── server.py             # FastMCP server, all tool handlers
├── types.py              # Pydantic models, enums, dataclasses
├── config.py             # config loading, defaults, validation
├── workspace.py          # .swarm/ directory management
├── tmux_manager.py       # libtmux wrapper + mock mode
├── registry.py           # worker state CRUD + persistence
├── provider_router.py    # CLI command builder per provider
├── message_queue.py      # task/result queue
├── worker_runner.py      # spawns provider commands, captures output
├── templates.py          # AGENTS.md + config file generation
├── planner.py            # task decomposition, deduplication
├── health.py             # staleness detection, heartbeat, TTL
├── tracking.py           # history, snapshots, cost tracking
├── archive.py            # session archival to markdown
├── reporting.py          # dashboard, stats, model recommendations
└── logging.py            # structured logging
```

---

## Roadmap

Items marked **done** are implemented and tested. The rest are hardening opportunities.

- [x] FastMCP stdio server with 33 tools
- [x] Multi-provider worker spawn (OpenCode, Claude Code, Codex)
- [x] Worker registry with persistent state
- [x] Tmux session management with mock mode
- [x] Task queue with provider concurrency caps
- [x] Cost tracking with budget enforcement
- [x] Snapshot-based undo/rollback
- [x] Health monitoring with staleness detection
- [x] Smart retry with failure classification
- [x] Task decomposition and planning
- [x] Wiki archival on cleanup
- [x] Live dashboard (text + JSON)
- [x] Performance stats and model recommendations
- [x] Trusted workflow engine with graduated trust
- [x] Semantic task similarity for deduplication
- [x] Provider-native token/cost ingestion
- [x] Live tmux dashboard pane renderer loop
- [x] Non-interactive permission denial parser pipeline

### Known Limitations

- **Permission monitoring is post-hoc, not preventive.** Providers are launched with `--dangerously-skip-permissions` / `bypassPermissions` flags for compatibility. The permission parser detects and logs denied paths from output, but cannot block access at the provider level. Remove bypass flags in `config.py` and `provider_router.py` to enforce strict permission boundaries.

- **Queue dispatch is not transactional.** When a queued worker is about to launch, it is removed from the pending queue before the tmux spawn. If the spawn fails, the task is lost — it is not re-queued. This is a simplification to avoid unbounded retry loops.

- **Duplicate `agent_id` has a race window.** The pre-spawn check for duplicate agent IDs is not atomic with the tmux launch. Two concurrent `swarm_spawn` calls with the same `agent_id` could both pass the check before either writes to the registry. This is unlikely in practice (MCP handles requests sequentially) but not guaranteed under all transports.

- **Cost recording is additive and not concurrency-safe.** Budget spent is computed as `record.status.budget_spent + amount` without file-level locking. In the current single-threaded async model this is safe, but concurrent MCP transports or multi-process access to the registry file could produce incorrect totals. The `parsed_cost` guard in `_process_result_file` prevents double-counting from repeated collect calls.

---

## License

MIT

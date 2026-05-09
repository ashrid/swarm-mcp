from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_worker_runner_persists_result_file(tmp_path: Path) -> None:
    result_file = tmp_path / "result.json"
    command = [
        sys.executable,
        "-m",
        "swarm_mcp.worker_runner",
        "--agent-id",
        "worker-1",
        "--task-id",
        "task-1",
        "--result-file",
        str(result_file),
        "--command",
        f"{sys.executable} -c \"print('hello from runner')\"",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    assert "hello from runner" in completed.stdout
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert payload["agent_id"] == "worker-1"
    assert payload["task_id"] == "task-1"
    assert payload["output"] == "hello from runner"
    assert payload["exit_code"] == 0

"""Wrapper process for provider commands.

Runs the underlying provider CLI command, mirrors output to stdout/stderr for tmux
visibility, and writes a structured result file on completion.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(command: str) -> tuple[int, str]:
    args = shlex.split(command)
    process = subprocess.Popen(
        args,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
        bufsize=1,
    )
    assert process.stdout is not None
    lines: list[str] = []
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(line)
    return_code = process.wait()
    return return_code, "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a provider command and persist its result.")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--command", required=True)
    args = parser.parse_args()

    return_code, output = run_command(args.command)
    payload = {
        "task_id": args.task_id,
        "agent_id": args.agent_id,
        "output": output.strip(),
        "exit_code": return_code,
        "completed_at": utc_now_iso(),
    }
    result_path = Path(args.result_file)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if return_code != 0:
        sys.exit(return_code)


if __name__ == "__main__":
    main()

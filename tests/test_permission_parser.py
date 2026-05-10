from __future__ import annotations

from swarm_mcp.permission_parser import (
    evaluate_permission_request,
    process_permission_batch,
    scan_for_permission_requests,
)


def test_scan_detects_permission_request() -> None:
    text = "Worker needs read access to /etc/passwd for analysis"
    requests = scan_for_permission_requests(text)
    assert len(requests) == 1
    assert requests[0]["path"] == "/etc/passwd"


def test_scan_detects_multiple_requests() -> None:
    text = "Permission required for /etc/passwd. Also needs access to /root/.bashrc"
    requests = scan_for_permission_requests(text)
    assert len(requests) == 2
    paths = {r["path"] for r in requests}
    assert "/etc/passwd" in paths
    assert "/root/.bashrc" in paths


def test_scan_no_requests() -> None:
    text = "Task completed successfully with no errors."
    requests = scan_for_permission_requests(text)
    assert len(requests) == 0


def test_auto_deny_system_path() -> None:
    result = evaluate_permission_request("/etc/passwd", "/home/user/project")
    assert result["status"] == "denied"
    assert "auto-deny" in result["reason"]


def test_workspace_path_requires_manual_review() -> None:
    result = evaluate_permission_request("./src/main.py", "/home/user/project")
    assert result["status"] == "pending"
    assert "workspace" in result["reason"]


def test_manual_review_outside_workspace() -> None:
    result = evaluate_permission_request("/home/other/project", "/home/user/project")
    assert result["status"] == "pending"
    assert "manual review" in result["reason"]


def test_process_batch_dedupes() -> None:
    requests = [
        {"path": "/etc/passwd", "reason": "test"},
        {"path": "/etc/passwd", "reason": "test2"},
        {"path": "./main.py", "reason": "test3"},
    ]
    results = process_permission_batch(requests, "/home/user/project")
    assert len(results) == 2
    statuses = {r["status"] for r in results}
    assert "denied" in statuses
    assert "pending" in statuses


def test_auto_deny_expands_home_path() -> None:
    import os

    home = os.path.expanduser("~")
    result = evaluate_permission_request(f"{home}/.ssh/id_rsa", "/home/user/project")
    assert result["status"] == "denied"
    assert "auto-deny" in result["reason"]


def test_scan_detects_permission_denied_colon_format() -> None:
    text = "Permission denied: /etc/passwd"
    requests = scan_for_permission_requests(text)
    assert len(requests) == 1
    assert requests[0]["path"] == "/etc/passwd"


def test_workspace_under_tmp_not_auto_denied() -> None:
    result = evaluate_permission_request("./src/main.py", "/tmp/myproject")
    assert result["status"] == "pending"
    assert "workspace" in result["reason"]

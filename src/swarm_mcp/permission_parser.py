"""Auto-deny policy engine for non-interactive permission handling."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PERMISSION_REQUEST_PATTERNS = [
    re.compile(
        r"permission\s+(?:requested|required|denied)\s+(?:for\s+)?"
        r"['\"]?([\w/.~\-]+)['\"]?(?:\s|$|\n|\.|,|;)",
        re.IGNORECASE,
    ),
    re.compile(
        r"permission\s+denied\s*:\s*"
        r"['\"]?([\w/.~\-]+)['\"]?(?:\s|$|\n|\.|,|;)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:needs?|requests?)\s+(?:read|write)\s+(?:access\s+)?(?:to\s+)?"
        r"['\"]?([\w/.~\-]+)['\"]?(?:\s|$|\n|\.|,|;)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:needs?|requests?)\s+access\s+to\s+"
        r"['\"]?([\w/.~\-]+)['\"]?(?:\s|$|\n|\.|,|;)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:file|path)\s+['\"]?([\w/.~\-]+)['\"]?\s+"
        r"(?:is\s+)?(?:not\s+)?(?:accessible|allowed|permitted)",
        re.IGNORECASE,
    ),
]

AUTO_DENY_PATHS = [
    "/etc/",
    "/root/",
    "/sys/",
    "/proc/",
    "/dev/",
    "/usr/bin/",
    "/usr/sbin/",
    "/boot/",
    "/var/log/",
    "~/.ssh/",
    "~/.gnupg/",
    "~/.aws/",
    "~/.config/",
    "/tmp/",
]

SENSITIVE_PATTERNS = [
    re.compile(r"\.env"),
    re.compile(r"\.swarm/"),
    re.compile(r"credentials"),
    re.compile(r"secret"),
    re.compile(r"token"),
    re.compile(r"key"),
    re.compile(r"password"),
]


def _is_sensitive(path_str: str) -> bool:
    lowered = path_str.lower()
    return any(pattern.search(lowered) for pattern in SENSITIVE_PATTERNS)


def _is_auto_deny(path_str: str, workspace_root: str = "") -> bool:
    import os

    normalized = path_str.lower().replace("\\", "/")
    expanded = os.path.expanduser(normalized)
    try:
        if workspace_root and not path_str.startswith("/"):
            base = Path(workspace_root).expanduser().resolve()
            resolved = str((base / expanded).resolve()).lower()
        else:
            resolved = str(Path(expanded).resolve()).lower()
    except (OSError, RuntimeError):
        resolved = expanded
    for deny_path in AUTO_DENY_PATHS:
        deny_lower = deny_path.lower()
        if normalized.startswith(deny_lower):
            return True
        expanded_deny = os.path.expanduser(deny_lower)
        if expanded.startswith(expanded_deny):
            return True
        if resolved.startswith(expanded_deny):
            return True
    return False


def _is_within_workspace(path_str: str, workspace_root: str) -> bool:
    try:
        workspace = Path(workspace_root).expanduser().resolve()
        if not path_str.startswith("/"):
            path = (workspace / path_str).expanduser().resolve()
        else:
            path = Path(path_str).expanduser().resolve()
        path.relative_to(workspace)
        return True
    except (ValueError, RuntimeError):
        return False


def scan_for_permission_requests(
    text: str, custom_patterns: list[str] | None = None
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    patterns = list(PERMISSION_REQUEST_PATTERNS)
    if custom_patterns:
        for custom in custom_patterns:
            try:
                compiled = re.compile(custom, re.IGNORECASE)
                if compiled.groups < 1:
                    continue
                patterns.append(compiled)
            except re.error:
                continue
    for pattern in patterns:
        for match in pattern.finditer(text):
            if match.lastindex is None:
                continue
            if "path" in match.groupdict():
                path_group = match.group("path")
            else:
                path_group = match.group(1)
            if path_group is None:
                continue
            path = path_group.strip("'\".,;:")
            requests.append({"path": path, "reason": "detected in output", "status": "pending"})
    return requests


def evaluate_permission_request(path: str, workspace_root: str) -> dict[str, Any]:
    if _is_within_workspace(path, workspace_root):
        if _is_sensitive(path):
            return {
                "path": path,
                "status": "pending",
                "reason": "sensitive path: manual review required",
            }
        return {"path": path, "status": "pending", "reason": "within workspace: manual review"}
    if _is_auto_deny(path, workspace_root):
        return {"path": path, "status": "denied", "reason": "auto-deny: system path"}
    if _is_sensitive(path):
        return {
            "path": path,
            "status": "pending",
            "reason": "sensitive path: manual review required",
        }
    return {"path": path, "status": "pending", "reason": "requires manual review"}


def process_permission_batch(
    requests: list[dict[str, Any]], workspace_root: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen = set()
    for req in requests:
        if not isinstance(req, dict):
            continue
        path = req.get("path", "")
        if not isinstance(path, str):
            continue
        path = path.strip()
        if not path:
            continue
        if path in seen:
            continue
        seen.add(path)
        results.append(evaluate_permission_request(path, workspace_root))
    return results

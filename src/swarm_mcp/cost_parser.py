"""Parse token usage and cost information from provider CLI output."""

from __future__ import annotations

import json
import re
from typing import Any


def _extract_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match and match.lastindex is not None:
        end_pos = match.end(1)
        if end_pos < len(text):
            next_char = text[end_pos]
            if next_char == "." and end_pos + 1 < len(text) and text[end_pos + 1].isdigit():
                return None
            if next_char.isalpha() or next_char == "_" or next_char == "e" or next_char == "E":
                return None
        raw = match.group(1)
        if raw.endswith(","):
            raw = raw[:-1]
            if raw.endswith(","):
                return None
        if "," in raw:
            parts = raw.split(",")
            if not parts[0].isdigit() or len(parts[0]) > 3:
                return None
            for part in parts[1:]:
                if not part.isdigit() or len(part) != 3:
                    return None
        return _safe_int(raw.replace(",", ""))
    return None


def _extract_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match and match.lastindex is not None:
        end_pos = match.end(1)
        if end_pos < len(text):
            next_char = text[end_pos]
            if next_char.isalpha() or next_char == "_" or next_char == "." or next_char == ",":
                return None
            if next_char in "eE" and (
                end_pos + 1 >= len(text) or text[end_pos + 1] not in "+-0123456789"
            ):
                return None
        raw = match.group(1)
        if "," in raw:
            int_part = raw.split(".")[0].split("e")[0].split("E")[0]
            parts = int_part.split(",")
            if not parts[0].isdigit() or len(parts[0]) > 3:
                return None
            for part in parts[1:]:
                if not part.isdigit() or len(part) != 3:
                    return None
        return _safe_float(raw.replace(",", ""))
    return None


def _safe_int(value: Any, max_value: int = 10_000_000_000) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, float):
            if not value.is_integer():
                return None
        result = int(value)
        if result < 0 or result > max_value:
            return None
        return result
    except (ValueError, TypeError, OverflowError, AttributeError):
        return None


def _safe_float(value: Any) -> float | None:
    import math

    try:
        if value is None or isinstance(value, bool):
            return None
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


_JSON_KEYS = frozenset(
    (
        "usage",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_cost",
        "total_cost_usd",
        "cost",
    )
)


def _collect_json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _try_add(data: dict[str, Any]) -> None:
        if any(k in data for k in _JSON_KEYS):
            fingerprint = json.dumps(data, sort_keys=True)
            if fingerprint not in seen:
                seen.add(fingerprint)
                objects.append(data)

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                _try_add(data)
                continue
        except (json.JSONDecodeError, ValueError):
            pass
        for end in range(len(line), 0, -1):
            try:
                data = json.loads(line[:end])
                if isinstance(data, dict):
                    _try_add(data)
                    break
            except (json.JSONDecodeError, ValueError):
                continue
    full = text
    depth = 0
    start = -1
    for i, ch in enumerate(full):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    data = json.loads(full[start : i + 1])
                    if isinstance(data, dict):
                        _try_add(data)
                except (json.JSONDecodeError, ValueError):
                    pass
                start = -1
    return objects


def parse_provider_output(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input_tokens": None,
        "output_tokens": None,
        "estimated_cost": None,
    }

    json_objects = _collect_json_objects(text)
    for json_data in json_objects:
        usage = json_data.get("usage", {})
        has_usage_dict = isinstance(usage, dict) and "usage" in json_data
        usage_cost_parsed = None
        usage_input_parsed = None
        usage_output_parsed = None
        if has_usage_dict:
            for key in ("input_tokens", "prompt_tokens"):
                if key in usage:
                    usage_input_parsed = _safe_int(usage[key])
                    if usage_input_parsed is not None:
                        result["input_tokens"] = (result["input_tokens"] or 0) + usage_input_parsed
                        break
            for key in ("output_tokens", "completion_tokens"):
                if key in usage:
                    usage_output_parsed = _safe_int(usage[key])
                    if usage_output_parsed is not None:
                        result["output_tokens"] = (
                            result["output_tokens"] or 0
                        ) + usage_output_parsed
                        break
            for key in ("total_cost", "total_cost_usd", "cost"):
                if key in usage and usage[key] is not None:
                    usage_cost_parsed = _safe_float(usage[key])
                    if usage_cost_parsed is not None:
                        result["estimated_cost"] = (
                            result["estimated_cost"] or 0.0
                        ) + usage_cost_parsed
                        break
        for key in ("input_tokens", "prompt_tokens"):
            if key in json_data and usage_input_parsed is None:
                parsed = _safe_int(json_data[key])
                if parsed is not None:
                    result["input_tokens"] = (result["input_tokens"] or 0) + parsed
                    break
        for key in ("output_tokens", "completion_tokens"):
            if key in json_data and usage_output_parsed is None:
                parsed = _safe_int(json_data[key])
                if parsed is not None:
                    result["output_tokens"] = (result["output_tokens"] or 0) + parsed
                    break
        usage_has_valid_cost = has_usage_dict and usage_cost_parsed is not None
        for key in ("total_cost_usd", "total_cost", "cost"):
            if key in json_data and json_data[key] is not None and not usage_has_valid_cost:
                cost_parsed = _safe_float(json_data[key])
                if cost_parsed is not None:
                    result["estimated_cost"] = (result["estimated_cost"] or 0.0) + cost_parsed
                    break
    input_patterns = [
        r"input tokens?[\s:]*([\d,]+)",
        r"prompt tokens?[\s:]*([\d,]+)",
        r"([\d,]+)\s*input tokens?",
        r"([\d,]+)\s*prompt tokens?",
        r"tokens[\s:]*([\d,]+)\s*input",
        r"input[\s:]*([\d,]+)",
    ]

    output_patterns = [
        r"output tokens?[\s:]*([\d,]+)",
        r"completion tokens?[\s:]*([\d,]+)",
        r"([\d,]+)\s*output tokens?",
        r"([\d,]+)\s*completion tokens?",
        r"tokens[\s:]*[\d,]+\s*input[\s,]*([\d,]+)\s*output",
        r"output[\s:]*([\d,]+)",
    ]

    _COST_INT = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
    _COST_NUM = _COST_INT + r"(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
    cost_patterns = [
        r"\b(?:total |estimated )?cost\b[\s:]*\$(" + _COST_NUM + r")",
        r"\b(?:total |estimated )?cost\b\s+is\s+\$(" + _COST_NUM + r")",
        r"\b(?:price|charge)\b[\s:]*\$(" + _COST_NUM + r")",
    ]

    if result["input_tokens"] is None:
        for pattern in input_patterns:
            value = _extract_int(pattern, text)
            if value is not None:
                result["input_tokens"] = value
                break

    if result["output_tokens"] is None:
        for pattern in output_patterns:
            value = _extract_int(pattern, text)
            if value is not None:
                result["output_tokens"] = value
                break

    if result["estimated_cost"] is None:
        for pattern in cost_patterns:
            cost_value = _extract_float(pattern, text)
            if cost_value is not None:
                result["estimated_cost"] = cost_value
                break

    return result

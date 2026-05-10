from __future__ import annotations

from swarm_mcp.cost_parser import parse_provider_output


def test_parse_opencodelike_output() -> None:
    text = "Analysis complete. Input tokens: 1523, Output tokens: 487"
    result = parse_provider_output(text)
    assert result["input_tokens"] == 1523
    assert result["output_tokens"] == 487
    assert result["estimated_cost"] is None


def test_parse_claude_like_output() -> None:
    text = "Prompt tokens: 2048, Completion tokens: 1024, Cost: $0.0042"
    result = parse_provider_output(text)
    assert result["input_tokens"] == 2048
    assert result["output_tokens"] == 1024
    assert result["estimated_cost"] == 0.0042


def test_parse_codex_like_output() -> None:
    text = "Tokens: 500 input, 150 output. Total cost: $0.0013 USD"
    result = parse_provider_output(text)
    assert result["input_tokens"] == 500
    assert result["output_tokens"] == 150
    assert result["estimated_cost"] == 0.0013


def test_parse_no_cost_info() -> None:
    text = "Task completed successfully with no errors."
    result = parse_provider_output(text)
    assert result["input_tokens"] is None
    assert result["output_tokens"] is None
    assert result["estimated_cost"] is None


def test_parse_only_input_tokens() -> None:
    text = "Input tokens: 1000"
    result = parse_provider_output(text)
    assert result["input_tokens"] == 1000
    assert result["output_tokens"] is None
    assert result["estimated_cost"] is None


def test_parse_mixed_case() -> None:
    text = "INPUT TOKENS: 2048, OUTPUT TOKENS: 512"
    result = parse_provider_output(text)
    assert result["input_tokens"] == 2048
    assert result["output_tokens"] == 512


def test_parse_comma_separated_numbers() -> None:
    text = "Input tokens: 1,234, Output tokens: 5,678"
    result = parse_provider_output(text)
    assert result["input_tokens"] == 1234
    assert result["output_tokens"] == 5678


def test_parse_embedded_in_text() -> None:
    text = """
    Worker finished processing.
    Summary: analyzed 42 files
    Input tokens: 3200
    Output tokens: 890
    Estimated cost: $0.0085
    Done.
    """
    result = parse_provider_output(text)
    assert result["input_tokens"] == 3200
    assert result["output_tokens"] == 890
    assert result["estimated_cost"] == 0.0085


def test_parse_single_line_json_not_double_counted() -> None:
    text = '{"input_tokens": 100, "output_tokens": 50, "total_cost": 0.001}'
    result = parse_provider_output(text)
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50
    assert result["estimated_cost"] == 0.001


def test_parse_jsonl_aggregates_tokens_and_cost() -> None:
    text = (
        '{"input_tokens": 100, "output_tokens": 50, "total_cost": 0.001}\n'
        '{"input_tokens": 200, "output_tokens": 100, "total_cost": 0.002}'
    )
    result = parse_provider_output(text)
    assert result["input_tokens"] == 300
    assert result["output_tokens"] == 150
    assert result["estimated_cost"] == 0.003


def test_parse_duplicate_json_lines_not_double_counted() -> None:
    text = (
        '{"input_tokens": 100, "output_tokens": 50, "total_cost": 0.001}\n'
        '{"input_tokens": 100, "output_tokens": 50, "total_cost": 0.001}'
    )
    result = parse_provider_output(text)
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50
    assert result["estimated_cost"] == 0.001


def test_parse_nested_usage_not_double_counted() -> None:
    text = (
        '{"usage":{"input_tokens":100,"output_tokens":50,"total_cost":0.001},'
        '"input_tokens":100,"output_tokens":50,"total_cost":0.001}'
    )
    result = parse_provider_output(text)
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50
    assert result["estimated_cost"] == 0.001


def test_parse_mixed_nested_tokens_top_level_cost() -> None:
    text = '{"usage":{"input_tokens":100,"output_tokens":50},"total_cost":0.001}'
    result = parse_provider_output(text)
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50
    assert result["estimated_cost"] == 0.001


def test_parse_usage_aliases_not_double_counted() -> None:
    text = (
        '{"usage":{"input_tokens":100,"prompt_tokens":100,'
        '"output_tokens":50,"completion_tokens":50}}'
    )
    result = parse_provider_output(text)
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50


def test_parse_usage_alias_fallback_when_first_invalid() -> None:
    text = (
        '{"usage":{"input_tokens":null,"prompt_tokens":123,'
        '"output_tokens":null,"completion_tokens":456}}'
    )
    result = parse_provider_output(text)
    assert result["input_tokens"] == 123
    assert result["output_tokens"] == 456


def test_parse_top_level_cost_when_usage_cost_invalid() -> None:
    text = '{"usage":{"total_cost":"n/a"},"total_cost":0.001}'
    result = parse_provider_output(text)
    assert result["estimated_cost"] == 0.001


def test_parse_usage_cost_alias_fallback_when_first_invalid() -> None:
    text = '{"usage":{"total_cost":"n/a","cost":0.01}}'
    result = parse_provider_output(text)
    assert result["estimated_cost"] == 0.01


def test_parse_top_level_alias_fallback_when_first_invalid() -> None:
    text = '{"input_tokens":null,"prompt_tokens":123}'
    result = parse_provider_output(text)
    assert result["input_tokens"] == 123


def test_parse_top_level_token_fallback_when_usage_invalid() -> None:
    text = (
        '{"usage":{"input_tokens":"n/a","output_tokens":"n/a"},'
        '"input_tokens":100,"output_tokens":50}'
    )
    result = parse_provider_output(text)
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50


def test_parse_multiline_json() -> None:
    text = '\n{\n  "input_tokens": 100,\n  "output_tokens": 50,\n  "total_cost": 0.001\n}\n'
    result = parse_provider_output(text)
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50
    assert result["estimated_cost"] == 0.001

"""Read the stream-json lines the agent CLI prints with `-p --output-format stream-json --verbose`.

One JSON object per line. The ones used here:

- ``{"type": "assistant", "message": {"id", "usage", "content": [{"type": "tool_use", ...}]}}``
- ``{"type": "result", "total_cost_usd", "usage", "num_turns", "is_error"}``, the last line of
  a run that ended by itself.

A run that was killed has no result line. Its tokens are then the sum of the usage of each
assistant message (counted once per message id), which is what the result line would have
added up too, except for the cost, which stays unknown (0.0) and is marked by ``result_seen``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: dict[str, int] = field(default_factory=dict)
    lines_written: int = 0
    num_turns: int = 0
    is_error: bool = False
    result_seen: bool = False
    bad_lines: int = 0

    @property
    def tool_calls_total(self) -> int:
        return sum(self.tool_calls.values())


def count_lines(text: str) -> int:
    """The lines in ``text``: a trailing newline does not add one."""
    return len(text.splitlines()) if text else 0


def written_lines(name: str, tool_input: dict[str, Any]) -> int:
    """The lines the agent itself wrote through one Write, Edit or MultiEdit call.

    Write counts its content, Edit its new string and MultiEdit the new strings of its edits.
    Lines written through Bash (heredocs, sed) are not counted: the diff size covers those.
    """
    if name == "Write":
        return count_lines(str(tool_input.get("content", "")))
    if name == "Edit":
        return count_lines(str(tool_input.get("new_string", "")))
    if name == "MultiEdit":
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            return sum(
                count_lines(str(edit.get("new_string", "")))
                for edit in edits
                if isinstance(edit, dict)
            )
    return 0


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _usage(usage: Any) -> tuple[int, int, int, int]:
    if not isinstance(usage, dict):
        return (0, 0, 0, 0)
    return (
        _int(usage.get("input_tokens")),
        _int(usage.get("output_tokens")),
        _int(usage.get("cache_read_input_tokens")),
        _int(usage.get("cache_creation_input_tokens")),
    )


def parse(lines: Iterable[str]) -> StreamStats:
    stats = StreamStats()
    seen_blocks: set[str] = set()
    usage_by_message: dict[str, tuple[int, int, int, int]] = {}
    anonymous = 0
    result_usage: tuple[int, int, int, int] | None = None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            stats.bad_lines += 1  # the last line of a killed run can be cut short
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "assistant" and isinstance(event.get("message"), dict):
            message = event["message"]
            message_id = message.get("id")
            if isinstance(message_id, str):
                usage_by_message[message_id] = _usage(message.get("usage"))
            else:
                anonymous += 1
                usage_by_message[f"anonymous-{anonymous}"] = _usage(message.get("usage"))
            content = message.get("content")
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                block_id = block.get("id")
                if isinstance(block_id, str):
                    if block_id in seen_blocks:
                        continue
                    seen_blocks.add(block_id)
                name = str(block.get("name", "unknown"))
                stats.tool_calls[name] = stats.tool_calls.get(name, 0) + 1
                tool_input = block.get("input")
                if isinstance(tool_input, dict):
                    stats.lines_written += written_lines(name, tool_input)
        elif kind == "result":
            stats.result_seen = True
            result_usage = _usage(event.get("usage"))
            cost = event.get("total_cost_usd", event.get("cost_usd", 0.0))
            stats.cost_usd = float(cost) if isinstance(cost, int | float) else 0.0
            stats.num_turns = _int(event.get("num_turns"))
            stats.is_error = bool(event.get("is_error"))
    if result_usage is None or not any(result_usage):
        result_usage = (
            sum(usage[0] for usage in usage_by_message.values()),
            sum(usage[1] for usage in usage_by_message.values()),
            sum(usage[2] for usage in usage_by_message.values()),
            sum(usage[3] for usage in usage_by_message.values()),
        )
    (
        stats.input_tokens,
        stats.output_tokens,
        stats.cache_read_tokens,
        stats.cache_creation_tokens,
    ) = result_usage
    return stats

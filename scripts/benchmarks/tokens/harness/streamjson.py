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
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

LIMIT_WORDS = re.compile(
    r"usage[ _-]?limit|rate[ _-]?limit|limit reached|limit exceeded|quota|too many requests"
    r"|\b429\b|resource[ _-]?exhausted|credit balance",
    re.IGNORECASE,
)
API_ERROR_WORDS = re.compile(
    r"overloaded|api[ _-]?error|\b(?:500|502|503|504|529)\b|internal server error"
    r"|service unavailable|connection (?:error|reset|refused)|timed? ?out|authentication",
    re.IGNORECASE,
)
_EPOCH = re.compile(r"\|\s*(\d{9,13})\b")
_RESETS = re.compile(r"resets?(?:\s+(?:at|on|in))?\s+([^.\n|]{2,60})", re.IGNORECASE)


def _iso(epoch: float) -> str:
    from datetime import UTC, datetime

    if epoch > 1e11:  # milliseconds
        epoch /= 1000
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def reset_time_in(text: str) -> str:
    """The reset time a limit message gives: an epoch after a bar, or the words after "resets"."""
    epoch = _EPOCH.search(text)
    if epoch:
        return _iso(float(epoch.group(1)))
    words = _RESETS.search(text)
    return words.group(1).strip() if words else ""


def _text_of(value: Any) -> str:
    """Every string in an error value (a string, or a dict with type, message, ...)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text_of(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_text_of(v) for v in value)
    return "" if value is None else str(value)


def classify(text: str) -> str:
    """ "usage_limit", "api_error" or "" for an error's type and message."""
    if LIMIT_WORDS.search(text):
        return "usage_limit"
    return "api_error" if API_ERROR_WORDS.search(text) else ""


def _note(stats: StreamStats, kind: str, text: str) -> None:
    """Keep the first error, but let a usage limit replace a plain API error."""
    if not kind or stats.error_kind == "usage_limit":
        return
    if stats.error_kind and kind != "usage_limit":
        return
    stats.error_kind, stats.error_message = kind, text.strip()[:300]
    stats.reset_time = reset_time_in(text) if kind == "usage_limit" else ""


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
    #: "" when the stream shows no error, else "usage_limit" (a usage or rate limit, HTTP 429)
    #: or "api_error" (an overloaded or other API error, or a result with is_error true).
    error_kind: str = ""
    error_message: str = ""
    #: When the limit lifts, if the message says (an ISO time, or the message's own words).
    reset_time: str = ""

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


def _error_event(stats: StreamStats, event: dict[str, Any], kind: object) -> None:
    """Error events: an error line, a rejected rate limit, a failed retry, an API error message."""
    if kind == "rate_limit_event":
        info = event.get("rate_limit_info")
        if isinstance(info, dict) and info.get("status") == "rejected":
            when = info.get("resetsAt")
            _note(stats, "usage_limit", "rate limit reached")
            if isinstance(when, int | float) and not stats.reset_time:
                stats.reset_time = _iso(float(when))
        return
    if kind == "system":
        if event.get("subtype") == "api_retry" and event.get("error_status") in (429, 529):
            _note(stats, classify(_text_of(event)) or "api_error", _text_of(event))
        return
    if kind == "assistant":
        text = _text_of([event.get("error"), event["message"].get("content")])
        _note(stats, classify(text) or "api_error", text)
        return
    text = _text_of(event.get("error", event))
    _note(stats, classify(text) or "api_error", text)


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
            if event.get("error"):
                _error_event(stats, event, "assistant")
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
        elif kind in ("error", "rate_limit_event", "system"):
            _error_event(stats, event, kind)
        elif kind == "result":
            stats.result_seen = True
            result_usage = _usage(event.get("usage"))
            cost = event.get("total_cost_usd", event.get("cost_usd", 0.0))
            stats.cost_usd = float(cost) if isinstance(cost, int | float) else 0.0
            stats.num_turns = _int(event.get("num_turns"))
            stats.is_error = bool(event.get("is_error"))
            text = _text_of([event.get("result"), event.get("error"), event.get("subtype")])
            if stats.is_error or event.get("api_error_status"):
                _note(stats, classify(text) or "api_error", text or "the result reports an error")
            else:  # it recovered (a retry worked): earlier error lines do not count
                stats.error_kind = stats.error_message = stats.reset_time = ""
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


def interruption(stats: StreamStats, exit_status: int | str, timed_out: bool) -> tuple[str, str]:
    """(kind, reason) when the agent was cut short, else ("", "").

    Kinds: ``usage_limit``, ``api_error``, ``no_result`` (the stream ended without a result
    line) and ``exit`` (a non-zero exit or a kill, without a result). A run that hit the time
    limit is not interrupted: the method counts the limit as part of the result.
    """
    if timed_out:
        return "", ""
    if stats.error_kind:
        return stats.error_kind, stats.error_message
    if not stats.result_seen:
        if exit_status not in (0, "not-run"):
            return "exit", f"the agent ended with status {exit_status} and no result"
        return "no_result", "the stream ended without a result"
    return "", ""

"""The data file: one JSON line per run, in data/runs.jsonl."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Where the raw data lives, next to the scripts.
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "runs.jsonl"


@dataclass
class RunRecord:
    run_id: str
    task: str
    condition: str
    index: int
    model: str
    started_at: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: dict[str, int] = field(default_factory=dict)
    tool_calls_total: int = 0
    wall_seconds: float = 0.0
    agent_lines_written: int = 0
    diff_lines_all: int = 0
    diff_lines_code: int = 0
    diff_files_all: int = 0
    diff_files_code: int = 0
    acceptance_passed: int = 0
    acceptance_total: int = 0
    build_ok: bool = False
    timed_out: bool = False
    exit_status: int | str = "not-run"
    result_seen: bool = False
    success: bool = False
    error: str = ""
    karni_commit: str = ""
    agent_version: str = ""
    #: The agent was cut short (a usage or rate limit, an API error, a kill): the run says
    #: nothing about the condition, so it is never counted and --resume runs it again.
    interrupted: bool = False
    interrupted_kind: str = ""
    interrupted_reason: str = ""
    reset_time: str = ""

    def finish(self) -> None:
        """Set ``success``: the run ended by itself, every test passed and the frontend builds."""
        self.success = (
            not self.interrupted
            and not self.timed_out
            and self.exit_status == 0
            and self.acceptance_total > 0
            and self.acceptance_passed == self.acceptance_total
            and self.build_ok
            and not self.error
        )

    def to_line(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def append(record: RunRecord, path: Path = DATA_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_line() + "\n")


def load(path: Path = DATA_FILE) -> list[dict[str, Any]]:
    """Every record in the file (lines that are not JSON objects are skipped)."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def done(rows: list[dict[str, Any]]) -> set[tuple[str, str, int]]:
    """The (task, condition, index) of every finished run: --resume skips these.

    An interrupted run is not finished; --resume runs it again.
    """
    return {
        (str(row.get("task")), str(row.get("condition")), int(row.get("index", 0)))
        for row in rows
        if not row.get("interrupted")
    }

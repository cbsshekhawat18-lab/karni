"""A stand-in for the agent CLI, to test the harness without spending any usage.

It prints stream-json lines shaped like the real ones and writes files in its working
directory. FAKE_AGENT_SLEEP=<seconds> makes it hang first (for the time limit),
FAKE_AGENT_EXIT=<code> sets its exit status, FAKE_AGENT_END=usage_limit|is_error|none ends the
stream with a usage-limit result, an is_error result or no result line at all,
FAKE_AGENT_ARGV=<file> records its arguments.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def emit(event: dict[str, object]) -> None:
    print(json.dumps(event), flush=True)


def main(argv: list[str]) -> int:
    log = os.environ.get("FAKE_AGENT_ARGV")
    if log:
        Path(log).write_text(json.dumps(argv))
    emit({"type": "system", "subtype": "init", "model": "fake", "tools": ["Write", "Edit", "Bash"]})
    note = "first line\nsecond line\nthird line\n"
    emit({
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "usage": {"input_tokens": 10, "output_tokens": 20,
                      "cache_read_input_tokens": 100, "cache_creation_input_tokens": 50},
            "content": [{"type": "tool_use", "id": "tu_1", "name": "Write",
                         "input": {"file_path": "fake_note.txt", "content": note}}],
        },
    })  # fmt: skip
    Path("fake_note.txt").write_text(note)
    time.sleep(float(os.environ.get("FAKE_AGENT_SLEEP", "0")))
    emit({
        "type": "assistant",
        "message": {
            "id": "msg_2",
            "usage": {"input_tokens": 5, "output_tokens": 7,
                      "cache_read_input_tokens": 150, "cache_creation_input_tokens": 0},
            "content": [
                {"type": "tool_use", "id": "tu_2", "name": "Edit",
                 "input": {"file_path": "fake_note.txt", "old_string": "first",
                           "new_string": "1st\nand"}},
                {"type": "tool_use", "id": "tu_3", "name": "Bash", "input": {"command": "ls"}},
            ],
        },
    })  # fmt: skip
    end = os.environ.get("FAKE_AGENT_END", "")
    if end == "usage_limit":
        emit({"type": "result", "subtype": "success", "is_error": True, "num_turns": 2,
              "result": "Usage limit reached|1893456000"})  # fmt: skip
        return int(os.environ.get("FAKE_AGENT_EXIT", "1"))
    if end == "is_error":
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
              "num_turns": 2, "result": "something broke"})  # fmt: skip
        return int(os.environ.get("FAKE_AGENT_EXIT", "1"))
    if end == "none":
        return int(os.environ.get("FAKE_AGENT_EXIT", "0"))
    emit({
        "type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
        "total_cost_usd": 0.0123,
        "usage": {"input_tokens": 15, "output_tokens": 27,
                  "cache_read_input_tokens": 250, "cache_creation_input_tokens": 50},
    })  # fmt: skip
    return int(os.environ.get("FAKE_AGENT_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

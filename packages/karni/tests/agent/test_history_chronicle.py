"""The built-in Gigai Chronicle provider against a fake ``chronicle`` on PATH.

The fake emits Chronicle's real ``--json`` envelope (apiVersion 1, shapes
from apps/cli/src/commands/context.ts and knowledge.ts, Markdown as rendered
by packages/core/src/knowledge/context-pack.ts) and every failure mode the
provider must absorb: exit 3, other exits, bad JSON, a foreign apiVersion,
an empty pack, a hang, a missing binary.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from karni.agent.history import compose, estimate_tokens
from karni.agent.history_chronicle import (
    ChronicleProvider,
    brief_from_decisions,
    brief_from_markdown,
    brief_from_pack,
    parse_envelope,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shebang fake binary")

MARKDOWN = """# Context for apps/events/models.py

_Assembled from your own AI-development history so your next prompt starts with
what was already asked and decided — paste this into your AI tool._

## What shaped this file

1. 2026-09-30 14:02  +12 −3  — "make events soft-deletable instead of hard delete"
2. 2026-09-28 09:15  +40 −0  — "add an Event model with title, starts_at, capacity"

## Why this file looks the way it does (Project Memory)

**Active decisions**
- Events are soft-deleted; never hard-delete (refunds reference them)

**Failed / superseded approaches (do NOT repeat)**
- Hard delete with ON DELETE CASCADE — reverted: it destroyed payment history

---
_Derived from the Chronicle record on this machine. Chronicle never calls a model;
this is your context, assembled — nothing left your machine._
"""

EXPECTED_BRIEF = """## Why this file looks the way it does (Project Memory)
**Active decisions**
- Events are soft-deleted; never hard-delete (refunds reference them)
**Failed / superseded approaches (do NOT repeat)**
- Hard delete with ON DELETE CASCADE — reverted: it destroyed payment history
## What shaped this file
1. 2026-09-30 14:02 +12 −3 — "make events soft-deletable instead of hard delete"
2. 2026-09-28 09:15 +40 −0 — "add an Event model with title, starts_at, capacity\""""

CONTEXT = {
    "apiVersion": 1,
    "command": "context",
    "file": "apps/events/models.py",
    "empty": False,
    "prompts": [
        {
            "eventId": "evt_01",
            "ts": "2026-09-30T14:02:11.000Z",
            "session": "ses_1",
            "text": "make events soft-deletable instead of hard delete",
            "churn": "+12 −3",
        }
    ],
    "knowledge": [
        {
            "kind": "decision",
            "text": "let's use soft delete for events",
            "eventId": "evt_01",
            "session": "ses_1",
            "ts": "2026-09-30T14:02:11.000Z",
            "role": "human",
            "confidence": "high",
        }
    ],
    "markdown": MARKDOWN,
}

EMPTY = {
    "apiVersion": 1,
    "command": "context",
    "file": "apps/events/models.py",
    "empty": True,
    "prompts": [],
    "knowledge": [],
    "markdown": (
        "# Context for apps/events/models.py\n\n_No captured history shaped this file yet — "
        "nothing to brief. Chronicle can only\nassemble context for work done while capture "
        "was running._\n"
    ),
}

KNOWLEDGE = {
    "apiVersion": 1,
    "command": "knowledge",
    "count": 2,
    "items": [
        {"kind": "decision", "text": "let's use Decimal for money", "ts": "2026-09-01T10:00Z"},
        {"kind": "decision", "text": "instead of   polling, use webhooks", "ts": "2026-09-20"},
    ],
}

FAKE = """#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls.jsonl"), "a") as log:
    log.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\\n")
sys.stderr.write("warning: workspace moved (noise that must be discarded)\\n")
mode = open(os.path.join(here, "mode")).read().strip()
if mode.startswith("exit"):
    sys.exit(int(mode[4:]))
if mode == "sleep":
    time.sleep(30)
if mode == "badjson":
    print("chronicle: something {{ not json")
    sys.exit(0)
command = sys.argv[1]
print(open(os.path.join(here, mode + "." + command + ".json")).read().strip())
"""


class FakeChronicle:
    def __init__(self, bin_dir: Path) -> None:
        self.bin = bin_dir

    def mode(self, mode: str) -> None:
        (self.bin / "mode").write_text(mode)

    def calls(self) -> list[dict[str, object]]:
        log = self.bin / "calls.jsonl"
        if not log.is_file():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.fixture
def chronicle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeChronicle:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "chronicle"
    script.write_text(FAKE.format(python=sys.executable))
    script.chmod(0o755)
    for mode, payloads in {
        "ok": {"context": CONTEXT, "knowledge": KNOWLEDGE},
        "empty": {"context": EMPTY, "knowledge": {**KNOWLEDGE, "count": 0, "items": []}},
        "foreign": {"context": {**CONTEXT, "apiVersion": 2}},
        "nomarkdown": {"context": {k: v for k, v in CONTEXT.items() if k != "markdown"}},
    }.items():
        for command, payload in payloads.items():
            (bin_dir / f"{mode}.{command}.json").write_text(json.dumps(payload))
    monkeypatch.setenv("PATH", str(bin_dir))
    fake = FakeChronicle(bin_dir)
    fake.mode("ok")
    return fake


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo whose .chronicle/ sits above the Karni project (Chronicle walks up)."""
    root = tmp_path / "repo"
    (root / ".chronicle").mkdir(parents=True)
    project = root / "backend"
    (project / "apps" / "events").mkdir(parents=True)
    return project


# detection (no subprocess)


def test_detect_walks_up_to_the_nearest_store(tmp_path: Path, repo: Path) -> None:
    provider = ChronicleProvider()
    assert provider.detect(repo)
    assert provider.store(repo) == (tmp_path / "repo" / ".chronicle").resolve()
    bare = tmp_path / "bare"
    bare.mkdir()
    assert not provider.detect(bare)
    (bare / ".chronicle").write_text("a file, not a store")
    assert not provider.detect(bare)


# the real envelope


@pytest.mark.history_provider
def test_context_runs_chronicle_from_the_repo_root(chronicle: FakeChronicle, repo: Path) -> None:
    brief = ChronicleProvider().context(repo, "apps/events/models.py")
    assert brief == EXPECTED_BRIEF
    (call,) = chronicle.calls()
    assert call["argv"] == ["context", "backend/apps/events/models.py", "--json", "--limit", "5"]
    assert Path(str(call["cwd"])).resolve() == repo.parent.resolve()


@pytest.mark.history_provider
def test_brief_puts_decisions_first_so_the_cap_keeps_them(
    chronicle: FakeChronicle, repo: Path
) -> None:
    block = compose(repo, "apps/events/models.py", providers=[ChronicleProvider()], max_tokens=120)
    assert block is not None and estimate_tokens(block) <= 120
    lines = block.split("\n")
    assert lines[0] == "HISTORY: apps/events/models.py (gigai-chronicle)"
    assert "Events are soft-deleted" in block
    assert "reverted: it destroyed payment history" in block
    assert "make events soft-deletable" not in block  # the prompt list went first
    assert lines[-1] == (
        "… truncated at ~120 tokens; full brief: chronicle context apps/events/models.py"
    )


@pytest.mark.history_provider
@pytest.mark.parametrize("mode", ["empty", "exit3", "exit1", "exit2", "badjson", "foreign"])
def test_every_failure_is_no_brief(
    chronicle: FakeChronicle, repo: Path, mode: str, capfd: pytest.CaptureFixture
) -> None:
    chronicle.mode(mode)
    assert ChronicleProvider().context(repo, "apps/events/models.py") is None
    assert ChronicleProvider().project_context(repo) is None
    assert len(chronicle.calls()) == 2  # it really ran
    out, err = capfd.readouterr()
    assert out == "" and err == ""  # chronicle's stderr is discarded


@pytest.mark.history_provider
def test_timeout_is_no_brief(chronicle: FakeChronicle, repo: Path) -> None:
    chronicle.mode("sleep")
    started = time.monotonic()
    assert ChronicleProvider(timeout=0.5).context(repo, "apps/events/models.py") is None
    assert time.monotonic() - started < 10


@pytest.mark.history_provider
def test_missing_binary_is_no_brief(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(repo))  # no chronicle anywhere: nothing is spawned
    assert ChronicleProvider().context(repo, "apps/events/models.py") is None
    assert ChronicleProvider(executable="definitely-not-installed").project_context(repo) is None


def test_no_store_never_runs_anything(tmp_path: Path) -> None:
    # The autouse guard fails this test if the provider tries to run chronicle.
    assert ChronicleProvider().context(tmp_path, "a.py") is None
    assert ChronicleProvider().project_context(tmp_path) is None


@pytest.mark.history_provider
def test_payload_without_markdown_uses_prompts_and_knowledge(
    chronicle: FakeChronicle, repo: Path
) -> None:
    chronicle.mode("nomarkdown")
    brief = ChronicleProvider().context(repo, "apps/events/models.py")
    assert brief == (
        "## Decisions & TODOs\n"
        "- [decision] let's use soft delete for events\n"
        "## What shaped this file\n"
        '1. 2026-09-30 +12 −3 — "make events soft-deletable instead of hard delete"'
    )


@pytest.mark.history_provider
def test_project_context_lists_decisions_newest_first(chronicle: FakeChronicle, repo: Path) -> None:
    assert ChronicleProvider().project_context(repo) == (
        "Recorded decisions (newest first):\n"
        "- 2026-09-20 instead of polling, use webhooks\n"
        "- 2026-09-01 let's use Decimal for money"
    )
    (call,) = chronicle.calls()
    assert call["argv"] == ["knowledge", "--type", "decision", "--json"]


# pure helpers


def test_parse_envelope() -> None:
    line = json.dumps(CONTEXT)
    assert parse_envelope(line + "\n", "context") == CONTEXT
    assert parse_envelope("note: something\n" + line, "context") == CONTEXT
    assert parse_envelope(line, "knowledge") is None
    assert parse_envelope("", "context") is None
    assert parse_envelope("[1, 2]", "context") is None


def test_markdown_compaction_is_stable_for_unknown_shapes() -> None:
    assert brief_from_markdown(MARKDOWN) == EXPECTED_BRIEF
    assert brief_from_markdown("# Context for x\n\nsome future line\n") == "some future line"
    assert brief_from_markdown(EMPTY["markdown"]) == ""  # type: ignore[arg-type]


def test_pack_and_decision_helpers_tolerate_junk() -> None:
    assert brief_from_pack(None, "nope") == ""
    assert brief_from_decisions([{"kind": "todo", "text": "x"}, "junk", {"text": " "}]) == ""
    assert full_command_examples() == [
        "chronicle context 'apps/my file.py'",
        "chronicle knowledge --type decision",
    ]


def full_command_examples() -> list[str]:
    provider = ChronicleProvider()
    return [
        provider.full_command(Path("."), "apps/my file.py"),
        provider.full_command(Path("."), None),
    ]

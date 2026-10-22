"""History providers: discovery, composition, the cap, rule conditions."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import pytest

from karni.agent import dump, history
from karni.agent.history import (
    CHARS_PER_TOKEN,
    CONDITIONS_ENV,
    ENTRY_POINT_GROUP,
    HISTORY_TOKEN_CAP,
    Discovered,
    cap_lines,
    compose,
    estimate_tokens,
)
from karni.agent.history_chronicle import ChronicleProvider
from karni.agent.rules import CONDITIONS, RULES

PACKAGE = Path(__file__).resolve().parents[2]


class FakeProvider:
    """A provider that keeps its "store" in ``<root>/.fakehistory/``."""

    def __init__(self, name: str = "fake", brief: str | None = "decided X", raises: bool = False):
        self.name = name
        self.brief = brief
        self.raises = raises
        self.calls: list[tuple[str, Any]] = []

    def detect(self, project_root: Path) -> bool:
        self.calls.append(("detect", project_root))
        return (Path(project_root) / ".fakehistory").is_dir()

    def context(self, project_root: Path, path: str) -> str | None:
        self.calls.append(("context", path))
        if self.raises:
            raise RuntimeError("boom")
        print("provider chatter that must never reach stdout")
        return self.brief

    def full_command(self, project_root: Path, path: str | None) -> str:
        return f"fakehist show {path}"


@pytest.fixture
def store(tmp_path: Path) -> Path:
    (tmp_path / ".fakehistory").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def _no_forced_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONDITIONS_ENV, raising=False)


# the cap


def test_estimate_matches_the_rules_budget_measure() -> None:
    assert CHARS_PER_TOKEN == 4
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_cap_lines_keeps_whole_lines_and_ends_with_the_hint() -> None:
    lines = ["HISTORY: f (x)", *(f"- line {i:03d} " + "x" * 40 for i in range(100))]
    capped = cap_lines(lines, 100, "… truncated")
    assert capped[0] == lines[0] and capped[-1] == "… truncated"
    assert capped[1:-1] == lines[1 : len(capped) - 1]  # a prefix of whole lines
    assert estimate_tokens("\n".join(capped)) <= 100
    assert cap_lines(lines[:3], 100, "… truncated") == lines[:3]  # fits: unchanged


def test_cap_lines_cuts_an_overlong_first_line_rather_than_dropping_everything() -> None:
    capped = cap_lines(["HISTORY: f (x)", "y" * 5000], 50, "… truncated")
    assert len(capped) == 3 and capped[1].endswith("…")
    assert estimate_tokens("\n".join(capped)) <= 50


# composition


def test_compose_heading_and_brief(store: Path) -> None:
    fake = FakeProvider(brief="Decided: soft delete.\n\nReverted: hard delete.\n")
    block = compose(store, "apps/events/models.py", providers=[fake])
    assert block == (
        "HISTORY: apps/events/models.py (fake)\nDecided: soft delete.\nReverted: hard delete."
    )


def test_compose_is_silent_without_a_store(tmp_path: Path) -> None:
    fake = FakeProvider()
    assert compose(tmp_path, "a.py", providers=[fake]) is None
    assert ("context", "a.py") not in fake.calls  # detect only; no brief requested


def test_compose_is_silent_when_the_provider_has_nothing(store: Path) -> None:
    assert compose(store, "a.py", providers=[FakeProvider(brief=None)]) is None
    assert compose(store, "a.py", providers=[FakeProvider(brief="  \n")]) is None
    assert compose(store, "a.py", providers=[FakeProvider(raises=True)]) is None


def test_compose_respects_the_cap(store: Path) -> None:
    brief = "\n".join(f"- decision {i}: " + "because " * 8 for i in range(200))
    block = compose(store, "a.py", providers=[FakeProvider(brief=brief)])
    assert block is not None
    assert estimate_tokens(block) <= HISTORY_TOKEN_CAP
    lines = block.split("\n")
    assert lines[0] == "HISTORY: a.py (fake)"
    assert lines[-1] == (
        f"… truncated at ~{HISTORY_TOKEN_CAP} tokens. Full brief: fakehist show a.py"
    )
    whole = [line.rstrip() for line in brief.split("\n")]
    assert lines[1:-1] == whole[: len(lines) - 2]  # whole lines, in order, nothing cut


def test_compose_shares_one_cap_across_providers(store: Path) -> None:
    long = "\n".join(f"- item {i} " + "z" * 30 for i in range(100))
    block = compose(store, "a.py", providers=[FakeProvider("one", brief=long), FakeProvider("two")])
    assert block is not None and estimate_tokens(block) <= HISTORY_TOKEN_CAP
    assert "(two)" not in block  # the budget was spent on the first brief

    both = compose(store, "a.py", providers=[FakeProvider("one"), FakeProvider("two")])
    assert both == "HISTORY: a.py (one)\ndecided X\nHISTORY: a.py (two)\ndecided X"


def test_compose_without_path_uses_project_context_when_offered(store: Path) -> None:
    fake = FakeProvider()
    assert compose(store, None, providers=[fake]) is None  # no project_context: nothing

    class WithProject(FakeProvider):
        def project_context(self, project_root: Path) -> str:
            return "Recorded decisions:\n- use Decimal for money"

    block = compose(store, None, providers=[WithProject()])
    assert block == "HISTORY: project (fake)\nRecorded decisions:\n- use Decimal for money"


def test_provider_output_never_reaches_stdout(store: Path, capfd: pytest.CaptureFixture) -> None:
    compose(store, "a.py", providers=[FakeProvider()])
    out, err = capfd.readouterr()
    assert out == "" and err == ""


# discovery


def test_builtin_chronicle_is_discovered_by_entry_point_and_fallback() -> None:
    found = history.discover()
    assert "gigai-chronicle" in found.names
    assert isinstance(
        next(p for p in found.providers if p.name == "gigai-chronicle"), ChronicleProvider
    )
    assert found.third_party() == ()


def _entry(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=ENTRY_POINT_GROUP)


def test_entry_points_win_and_broken_ones_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    module = type(sys)("fake_history_mod")
    module.Provider = FakeProvider  # type: ignore[attr-defined]
    module.instance = FakeProvider("instance")  # type: ignore[attr-defined]
    module.factory = lambda: FakeProvider("factory")  # type: ignore[attr-defined]
    module.junk = object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_history_mod", module)
    monkeypatch.setattr(
        history,
        "_entry_points",
        lambda: [
            _entry("fake", "fake_history_mod:Provider"),
            _entry("instance", "fake_history_mod:instance"),
            _entry("factory", "fake_history_mod:factory"),
            _entry("junk", "fake_history_mod:junk"),
            _entry("missing", "no_such_module_xyz:Provider"),
        ],
    )
    found = history.discover()
    assert found.names == ["factory", "fake", "gigai-chronicle", "instance"]
    assert {p.name for p in found.third_party()} == {"factory", "fake", "instance"}
    assert any(e.startswith("junk ") and "not a history provider" in e for e in found.errors)
    assert any(e.startswith("missing ") and "ModuleNotFoundError" in e for e in found.errors)


def test_an_entry_point_named_like_the_builtin_replaces_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = type(sys)("fake_history_mod2")
    module.Provider = lambda: FakeProvider("gigai-chronicle")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_history_mod2", module)
    own = _entry("gigai-chronicle", "karni.agent.history_chronicle:ChronicleProvider")
    theirs = _entry("gigai-chronicle", "fake_history_mod2:Provider")
    for order in ([own, theirs], [theirs, own], [theirs]):
        monkeypatch.setattr(history, "_entry_points", lambda order=order: order)
        found = history.discover()
        (provider,) = found.providers
        assert isinstance(provider, FakeProvider), order  # karni's own registration loses
        assert found.errors == (), order


def test_discovered_third_party_excludes_builtins() -> None:
    found = Discovered((ChronicleProvider(), FakeProvider("x")))
    assert [p.name for p in found.third_party()] == ["x"]


# conditions and the conditional rule


def test_every_conditional_rule_names_a_known_condition() -> None:
    conditional = [rule for rule in RULES if rule.when]
    assert conditional, "the history rule exists"
    assert {rule.when for rule in conditional} <= set(CONDITIONS)


def test_history_rule_only_when_a_store_is_detected(tmp_path: Path) -> None:
    assert "K008" not in {r["code"] for r in dump(tmp_path)["rules"]}
    assert dump(tmp_path)["conditions"] == []
    (tmp_path / ".chronicle").mkdir()  # detection is a directory walk: nothing runs
    data = dump(tmp_path)
    assert data["conditions"] == ["history"]
    k008 = next(r for r in data["rules"] if r["code"] == "K008")
    assert "karni context --with-history <file>" in k008["rule"]
    assert "reverted" in k008["rule"]
    assert "K008" not in {r["code"] for r in dump(None)["rules"]}  # no project, no store


def test_store_above_the_project_counts(tmp_path: Path) -> None:
    (tmp_path / ".chronicle").mkdir()
    project = tmp_path / "services" / "web"
    project.mkdir(parents=True)
    assert history.active_conditions(project) == frozenset({"history"})


def test_conditions_env_is_an_escape_hatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".chronicle").mkdir()
    monkeypatch.setenv(CONDITIONS_ENV, "")
    assert "K008" not in {r["code"] for r in dump(tmp_path)["rules"]}
    monkeypatch.setenv(CONDITIONS_ENV, "history")
    assert "K008" in {r["code"] for r in dump(None)["rules"]}


def test_overrides_can_disable_the_history_rule(tmp_path: Path) -> None:
    (tmp_path / ".chronicle").mkdir()
    (tmp_path / "karni.rules.py").write_text('DISABLE = ["K008"]\n')
    assert "K008" not in {r["code"] for r in dump(tmp_path)["rules"]}


@pytest.mark.parametrize("module", ["karni.agent.history", "karni.agent.history_chronicle"])
def test_import_light(module: str) -> None:
    """Stdlib only: the CLI loads these without Django or a project."""
    code = (
        f"import sys, {module}; "
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
        "('django', 'rest_framework', 'celery')); "
        "assert not bad, bad"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PACKAGE,
        capture_output=True,
        text=True,
        env={"PATH": "", "PYTHONPATH": str(PACKAGE)},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_history_never_imports_chronicle() -> None:
    for name in ("history.py", "history_chronicle.py"):
        source = (PACKAGE / "karni" / "agent" / name).read_text()
        assert "import chronicle" not in source and "from chronicle" not in source
        assert "gigaichronicle" not in source.replace("Gigai Chronicle", "")

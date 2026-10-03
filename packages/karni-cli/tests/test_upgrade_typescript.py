"""The jscodeshift runner and the data-driven ``RenameExport`` codemod.

``RenameExport(module="@karni/ui", old="DataTable", new="ResourceTable")`` here
is a FIXTURE, not a shipped change: @karni/ui has had no breaking change yet.
It proves the first real one is a single line of data.

Most tests run a fake jscodeshift (``KARNI_JSCODESHIFT``), so the suite never
needs Node.js or the network. One test runs the real, pinned jscodeshift, and
only when it is already in the npx cache (checked offline, with a timeout).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from karni_cli.upgrades import typescript
from karni_cli.upgrades.typescript import JSCODESHIFT_VERSION, RenameExport

FIXTURE = RenameExport(module="@karni/ui", old="DataTable", new="ResourceTable")

SCREEN = """\
import { DataTable, Page } from "@karni/ui";

export function Screen({ rows }: { rows: number[] }) {
  return (
    <Page>
      <DataTable rows={rows} />
    </Page>
  );
}
"""
SCREEN_AFTER = SCREEN.replace("DataTable", "ResourceTable")

FAKE = textwrap.dedent(
    """\
    import json, os, re, sys
    args = sys.argv[1:]
    options = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
    files = [a for a in args if not a.startswith("--")]
    with open(os.environ["FAKE_JSCODESHIFT_LOG"], "a") as log:
        log.write(json.dumps(args) + "\\n")
    old, new = options["karni-from"], options["karni-to"]
    for name in files:
        with open(name) as handle:
            text = handle.read()
        changed, count = re.subn(r"\\b%s\\b" % re.escape(old), new, text)
        if count:
            with open(name, "w") as handle:
                handle.write(changed)
            print(" REP %s karni-count %d" % (name, count))
    if os.environ.get("FAKE_JSCODESHIFT_FAIL"):
        print("ERR boom", file=sys.stderr)
        sys.exit(1)
    """
)


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "screen.tsx").write_text(SCREEN)
    (src / "util.ts").write_text(
        'import { DataTable } from "@karni/ui";\nexport const T = DataTable;\n'
    )
    (src / "other.ts").write_text("export const DataTable = 1; // its own, not the UI kit\n")
    (src / "types.d.ts").write_text('import { DataTable } from "@karni/ui";\n')
    modules = tmp_path / "frontend" / "node_modules" / "@karni" / "ui"
    modules.mkdir(parents=True)
    (modules / "index.ts").write_text('import { DataTable } from "@karni/ui";\n')
    return tmp_path


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "fake_jscodeshift.py"
    script.write_text(FAKE)
    log = tmp_path / "jscodeshift.log"
    monkeypatch.setenv("KARNI_JSCODESHIFT", f"{sys.executable} {script}")
    monkeypatch.setenv("FAKE_JSCODESHIFT_LOG", str(log))
    return log


def test_the_runner_is_the_pinned_jscodeshift_through_npx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KARNI_JSCODESHIFT", raising=False)
    monkeypatch.setattr(typescript.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert typescript.jscodeshift_command() == [
        "/usr/bin/npx",
        "--yes",
        f"jscodeshift@{JSCODESHIFT_VERSION}",
    ]
    monkeypatch.setenv("KARNI_JSCODESHIFT", "node /opt/jscodeshift/bin/jscodeshift.js")
    assert typescript.jscodeshift_command() == ["node", "/opt/jscodeshift/bin/jscodeshift.js"]


def test_rename_export_runs_once_per_parser_on_candidate_files(frontend: Path, fake: Path) -> None:
    outcome = FIXTURE.apply(frontend)
    assert outcome.skipped == ""
    assert outcome.files == {"frontend/src/screen.tsx": 2, "frontend/src/util.ts": 2}
    assert (frontend / "frontend/src/screen.tsx").read_text() == SCREEN_AFTER
    # Files without the module and the name, declaration files and node_modules
    # are never handed to jscodeshift.
    assert "DataTable" in (frontend / "frontend/src/other.ts").read_text()
    calls = [json.loads(line) for line in fake.read_text().splitlines()]
    assert [[a for a in call if a.startswith("--parser")] for call in calls] == [
        ["--parser=tsx"],
        ["--parser=ts"],
    ]
    tsx_call = calls[0]
    assert tsx_call[-1] == "frontend/src/screen.tsx"
    assert any(a.endswith("transforms/rename-export.cjs") for a in tsx_call)
    assert {"--karni-module=@karni/ui", "--karni-from=DataTable", "--karni-to=ResourceTable"} <= (
        set(tsx_call)
    )


def test_nothing_to_change_needs_no_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KARNI_JSCODESHIFT", raising=False)
    monkeypatch.setattr(typescript.shutil, "which", lambda name: None)
    (tmp_path / "app.ts").write_text('import { Page } from "@karni/ui";\n')
    outcome = FIXTURE.apply(tmp_path)
    assert (outcome.files, outcome.skipped) == ({}, "")


def test_without_node_the_codemod_is_skipped_with_a_reason(
    frontend: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KARNI_JSCODESHIFT", raising=False)
    monkeypatch.setattr(typescript.shutil, "which", lambda name: None)
    outcome = FIXTURE.apply(frontend)
    assert outcome.files == {}
    assert "Node.js (npx) not found" in outcome.skipped
    assert "2 TypeScript file(s)" in outcome.skipped
    assert (frontend / "frontend/src/screen.tsx").read_text() == SCREEN


def test_a_failing_run_restores_every_file(
    frontend: Path, fake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_JSCODESHIFT_FAIL", "1")
    outcome = FIXTURE.apply(frontend)
    assert outcome.files == {}
    assert "jscodeshift failed (exit 1): ERR boom" in outcome.skipped
    assert (frontend / "frontend/src/screen.tsx").read_text() == SCREEN


def test_a_hanging_run_times_out_and_restores(
    frontend: Path, fake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def hang(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["stdin"] is subprocess.DEVNULL and kwargs["timeout"] == typescript.TIMEOUT
        (frontend / "frontend/src/screen.tsx").write_text("half-written")
        raise subprocess.TimeoutExpired("jscodeshift", typescript.TIMEOUT)

    monkeypatch.setattr(typescript.subprocess, "run", hang)
    outcome = FIXTURE.apply(frontend)
    assert "jscodeshift failed (exit 124): timed out after 600s" in outcome.skipped
    assert (frontend / "frontend/src/screen.tsx").read_text() == SCREEN


def _cached_jscodeshift() -> list[str] | None:
    """The pinned jscodeshift, only if npx already has it: no network, no prompt."""
    npx = shutil.which("npx")
    if npx is None:
        return None
    command = [npx, "--no", "--prefer-offline", f"jscodeshift@{JSCODESHIFT_VERSION}"]
    try:
        probe = subprocess.run(
            [*command, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return command if probe.returncode == 0 else None


def test_the_real_transform(frontend: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    command = _cached_jscodeshift()
    if command is None:
        pytest.skip(f"jscodeshift@{JSCODESHIFT_VERSION} is not in the npx cache (or no Node.js)")
    monkeypatch.setenv("KARNI_JSCODESHIFT", " ".join(command))
    shadowed = (
        'import { DataTable as Grid } from "@karni/ui";\n'
        'export { DataTable } from "@karni/ui";\n'
        "export function f() {\n  const DataTable = 1;\n  return [DataTable, Grid];\n}\n"
    )
    (frontend / "frontend/src/alias.ts").write_text(shadowed)
    outcome = FIXTURE.apply(frontend)
    assert outcome.skipped == ""
    assert (frontend / "frontend/src/screen.tsx").read_text() == SCREEN_AFTER
    assert (frontend / "frontend/src/alias.ts").read_text() == (
        'import { ResourceTable as Grid } from "@karni/ui";\n'
        'export { ResourceTable as DataTable } from "@karni/ui";\n'
        "export function f() {\n  const DataTable = 1;\n  return [DataTable, Grid];\n}\n"
    )
    assert outcome.files["frontend/src/screen.tsx"] == 2
    assert FIXTURE.apply(frontend).files == {}  # idempotent

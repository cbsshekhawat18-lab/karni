"""Generated agent adapters: formats, sync semantics, regeneration identity, coverage."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import pytest
import yaml

from karni_cli import agent_data
from karni_cli.adapters import (
    GENERATED_MARK,
    MODULES_DIR,
    load_registry,
    render_all,
    sync,
)
from karni_cli.main import app
from karni_cli.project import CliError
from karni_cli.rules_render import render_procedure, render_prompts_doc
from karni_cli.upgrades.legacy_agent_files import LEGACY_FILES

from .conftest import REPO_ROOT, TEMPLATE

ADAPTER_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/karni.mdc",
    ".windsurf/rules/karni.md",
    ".github/copilot-instructions.md",
    ".clinerules/karni.md",
    "CONVENTIONS.md",
    ".junie/AGENTS.md",
}
PROCEDURES = ("new-model", "new-page", "add-module", "new-module")
COMMAND_FILES = {
    f"{directory}/{name}{suffix}"
    for directory, suffix in (
        (".claude/commands", ".md"),
        (".cursor/commands", ".md"),
        (".windsurf/workflows", ".md"),
        (".github/prompts", ".prompt.md"),
    )
    for name in PROCEDURES
}
FRAGMENT = "## Payments (karni-payments)\n- Never call provider SDKs directly.\n"


def _generated(project: Path) -> dict[str, str]:
    found = {}
    for path in project.rglob("*"):
        rel = path.relative_to(project).as_posix()
        if path.is_file() and not rel.startswith(("frontend/", ".karni/")):
            text = path.read_text(errors="replace")
            if GENERATED_MARK in text:
                found[rel] = text
    return found


def _frontmatter(text: str) -> dict[str, object] | None:
    if not text.startswith("---\n"):
        return None
    head = text.split("---\n", 2)[1]
    loaded = yaml.safe_load(head)
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture
def new_project(runner, tmp_path: Path, monkeypatch) -> Path:
    """`karni new`, exactly as a user runs it."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = runner.invoke(app, ["new", "Acme Board", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "24 agent adapter files" in result.output
    project = tmp_path / "acme_board"
    monkeypatch.chdir(project)
    return project


def test_template_carries_no_hand_written_guidance() -> None:
    slug = TEMPLATE / "{{cookiecutter.project_slug}}"
    for rel in [*ADAPTER_FILES, ".cursorrules", ".claude/commands"]:
        assert not (slug / rel).exists(), rel


def test_new_generates_every_adapter_and_command(new_project: Path) -> None:
    assert set(_generated(new_project)) == ADAPTER_FILES | COMMAND_FILES


def test_delete_all_adapters_then_sync_regenerates_identically(runner, new_project) -> None:
    """VERIFY step: delete every adapter file, `karni rules sync`, byte-identical result."""
    (new_project / MODULES_DIR).mkdir(parents=True)
    (new_project / MODULES_DIR / "payments.md").write_text(FRAGMENT)
    (new_project / "karni.rules.py").write_text(
        'ADD = [{"code": "P001", "rule": "Money is Decimal."}]\n'
        'ADAPTERS = {"paths": {"windsurf": ".devin/rules/karni.md"}}\n'
    )
    assert runner.invoke(app, ["rules", "sync"]).exit_code == 0
    before = _generated(new_project)
    assert ".devin/rules/karni.md" in before and ".windsurf/rules/karni.md" not in before
    assert "<!-- karni:module:payments -->" in before["AGENTS.md"]

    for rel in before:
        (new_project / rel).unlink()
    assert _generated(new_project) == {}

    result = runner.invoke(app, ["rules", "sync"])
    assert result.exit_code == 0, result.output
    assert _generated(new_project) == before
    check = runner.invoke(app, ["rules", "sync", "--check"])
    assert check.exit_code == 0, check.output


def test_formats_match_each_tools_convention(new_project: Path) -> None:
    files = _generated(new_project)
    registry = load_registry()
    for rel, text in files.items():
        assert text.count("\n") <= registry.max_lines, rel
        assert text.endswith("\n") and not text.endswith("\n\n"), rel

    assert files["CLAUDE.md"].splitlines()[-1] == "@AGENTS.md"
    cursor = _frontmatter(files[".cursor/rules/karni.mdc"])
    assert cursor == {
        "description": "Karni project conventions: run karni context and karni rules "
        "before any work",
        "globs": None,
        "alwaysApply": True,
    }
    assert _frontmatter(files[".windsurf/rules/karni.md"]) == {"trigger": "always_on"}
    for rel in ("AGENTS.md", ".github/copilot-instructions.md", ".clinerules/karni.md"):
        assert _frontmatter(files[rel]) is None, rel
    assert "aider --read CONVENTIONS.md" in files["CONVENTIONS.md"]

    claude = files[".claude/commands/new-model.md"]
    assert set(_frontmatter(claude) or {}) == {"description", "argument-hint"}
    assert "$ARGUMENTS" in claude
    assert _frontmatter(files[".cursor/commands/new-model.md"]) is None
    assert set(_frontmatter(files[".windsurf/workflows/new-page.md"]) or {}) == {"description"}
    prompt = files[".github/prompts/add-module.prompt.md"]
    assert (_frontmatter(prompt) or {})["agent"] == "agent"
    assert "${input:request:what to add}" in prompt


def test_every_adapter_says_the_same_thing(new_project: Path) -> None:
    files = _generated(new_project)
    bodies = {
        rel: text.split("---\n", 2)[-1] if text.startswith("---\n") else text
        for rel, text in files.items()
        if rel in ADAPTER_FILES and rel not in ("CLAUDE.md", "CONVENTIONS.md")
    }
    assert len(set(bodies.values())) == 1, sorted(bodies)
    body = next(iter(bodies.values()))
    assert "`karni context`" in body and "`karni rules`" in body
    assert 15 <= body.count("\n") <= 25  # thin: ~15 lines of guidance


def test_registry_records_verified_sources() -> None:
    text = (resources.files("karni_cli") / "agent_adapters.toml").read_text()
    blocks = re.split(r"^\[\[(?:adapter|commands)\]\]$", text, flags=re.MULTILINE)[1:]
    registry = load_registry()
    assert len(blocks) == len(registry.adapters) + len(registry.commands)
    for block in blocks:
        assert "verified 2026-10-02" in block, block[:60]
        assert "Source:" in block, block[:60]


def test_check_detects_edits_missing_and_obsolete_files(runner, new_project) -> None:
    assert runner.invoke(app, ["rules", "sync", "--check"]).exit_code == 0

    agents = new_project / "AGENTS.md"
    agents.write_text(agents.read_text() + "edited\n")
    (new_project / ".clinerules" / "karni.md").unlink()
    stale = new_project / ".claude" / "commands" / "old-procedure.md"
    stale.write_text(f"<!-- {GENERATED_MARK} -->\n")
    result = runner.invoke(app, ["rules", "sync", "--check"])
    assert result.exit_code == 1
    for rel in ("AGENTS.md", ".clinerules/karni.md", ".claude/commands/old-procedure.md"):
        assert f"stale: {rel}" in result.output
    assert "edited" in agents.read_text()  # --check never writes

    assert runner.invoke(app, ["rules", "sync"]).exit_code == 0
    assert not stale.exists()
    assert runner.invoke(app, ["rules", "sync", "--check"]).exit_code == 0


def test_sync_never_clobbers_hand_written_files(runner, new_project) -> None:
    agents = new_project / "AGENTS.md"
    agents.write_text("# Our own agent notes\n")
    result = runner.invoke(app, ["rules", "sync"])
    assert result.exit_code == 1
    assert "skipped AGENTS.md" in result.output
    assert agents.read_text() == "# Our own agent notes\n"

    forced = runner.invoke(app, ["rules", "sync", "--force"])
    assert forced.exit_code == 0, forced.output
    assert GENERATED_MARK in agents.read_text()
    backup = new_project / ".karni" / "backup" / "AGENTS.md"
    assert backup.read_text() == "# Our own agent notes\n"


def test_disable_and_move_adapters(runner, new_project) -> None:
    (new_project / "karni.rules.py").write_text(
        'ADAPTERS = {"disable": ["copilot-prompts", "aider"], '
        '"paths": {"cline": ".cline/rules/karni.md"}}\n'
    )
    assert runner.invoke(app, ["rules", "sync", "--check"]).exit_code == 1
    assert runner.invoke(app, ["rules", "sync"]).exit_code == 0
    files = _generated(new_project)
    assert not any(rel.startswith(".github/prompts/") for rel in files)
    assert "CONVENTIONS.md" not in files
    assert ".cline/rules/karni.md" in files and ".clinerules/karni.md" not in files

    (new_project / "karni.rules.py").write_text('ADAPTERS = {"disable": ["emacs"]}\n')
    bad = runner.invoke(app, ["rules", "sync"])
    assert bad.exit_code != 0


def test_claude_falls_back_to_full_body_without_agents_md(new_project) -> None:
    (new_project / "karni.rules.py").write_text('ADAPTERS = {"disable": ["agents-md"]}\n')
    files = render_all(new_project, agent_data.load(new_project))
    assert "@AGENTS.md" not in files["CLAUDE.md"]
    assert "`karni rules`" in files["CLAUDE.md"]


def test_module_guidance_degrades_to_pointers_past_the_cap(new_project) -> None:
    modules = new_project / MODULES_DIR
    modules.mkdir(parents=True)
    for i in range(8):
        (modules / f"mod{i}.md").write_text("\n".join(f"- rule {j}" for j in range(14)) + "\n")
    files = render_all(new_project, agent_data.load(new_project))
    agents = files["AGENTS.md"]
    assert agents.count("\n") <= 100
    assert "karni:module:mod0" not in agents
    assert "- mod7: run `karni rules`" in agents


def test_overlong_project_input_fails_loudly(new_project) -> None:
    long_note = "x" * 50
    modules = new_project / MODULES_DIR
    modules.mkdir(parents=True)
    for i in range(120):
        (modules / f"m{i:03d}.md").write_text(long_note)
    with pytest.raises(CliError, match="cap 100"):
        render_all(new_project, agent_data.load(new_project))


def test_sync_requires_a_project(runner, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["rules", "sync"]).exit_code != 0


def test_docs_prompts_block_is_fresh() -> None:
    docs = (REPO_ROOT / "docs" / "agents.md").read_text()
    assert render_prompts_doc(agent_data.load(None)) in docs


# functional identity with the audited (pre-retrofit) guidance

#: (legacy file, statement as the old file said it, where it lives now, a phrase
#: the new source must contain). Every statement of the audited files is listed.
COVERAGE = [
    ("AGENTS.md", "Karni already implements everything generic", "K301", "everything generic"),
    ("AGENTS.md", "Extending Karni is always cheaper than reinventing it.", "K301", "cheaper"),
    ("AGENTS.md", "Run `karni context` before reading any files.", "K001", "before reading any"),
    ("AGENTS.md", "viewsets, UI components, hooks and installed modules", "K001", "hooks"),
    ("AGENTS.md", "Trust it.", "K001", "trust it"),
    (
        "AGENTS.md",
        "Auth flows, user models, admin registration, serializers, routers, settings,",
        "K302",
        "auth flows, user models, admin registration, serializers, routers, settings",
    ),
    (
        "AGENTS.md",
        "Docker/Compose config, Celery config, HTML tables, forms, or detail views.",
        "K302",
        "docker/compose config, celery config, html tables, forms, or detail views",
    ),
    (
        "AGENTS.md",
        "If you think you need one, you need an override",
        "K302",
        "you need an override on an existing karni base",
    ),
    (
        "AGENTS.md",
        "Models inherit `karni.models.BaseModel` (or `SoftDeleteModel`).",
        "K101",
        "karni.models.basemodel",
    ),
    (
        "AGENTS.md",
        "Viewsets inherit `karni.api.BaseViewSet` — usually just `model = X`.",
        "K102",
        "usually just `model = x`",
    ),
    ("AGENTS.md", "Never hand-roll a table or form.", "K201", "never hand-roll a table or form"),
    ("AGENTS.md", "`ResourceForm`, `ResourceDetail`, ...)", "K201", "resourcedetail"),
    ("AGENTS.md", "Page files stay at 50 lines or fewer", "K202", "50 lines or fewer"),
    ("AGENTS.md", "use the component's props", "K202", "use the component's props"),
    (
        "AGENTS.md",
        "After any model change: `make migrate && karni types`.",
        "K003",
        "make migrate && karni types",
    ),
    (
        "AGENTS.md",
        "Run `karni check` before committing — every rule fails the build.",
        "K004",
        "`karni check` before committing",
    ),
    (
        "AGENTS.md",
        "are inline and REQUIRE a reason, e.g. `# karni: allow(raw-sql): <why>`.",
        "K005",
        "# karni: allow(<rule-id>): <why>",
    ),
    (
        "AGENTS.md",
        "override props / hooks (`columns`, `fields`, `slots`, `AdminMeta`, `APIMeta`,",
        "K303",
        "`columns`, `fields`, `slots`, `adminmeta`, `apimeta`",
    ),
    (
        "AGENTS.md",
        "overridable methods). Do not create a parallel variant.",
        "K303",
        "do not create a parallel variant",
    ),
    (
        "AGENTS.md",
        "Do not introduce a state library, form library, table library, HTTP client or",
        "K304",
        "state library, form library, table library, http client or css framework",
    ),
    ("AGENTS.md", "Zod, Tailwind, Radix via @karni/ui).", "K304", "zod, tailwind, radix"),
    (
        "AGENTS.md",
        "Backend app: `<app>/models.py`, `<app>/viewsets.py` — nothing else per entity.",
        "K305",
        "nothing else",
    ),
    ("AGENTS.md", "Frontend pages: `frontend/src/pages/`.", "K306", "frontend/src/pages/"),
    (
        "AGENTS.md",
        "/add-module, /new-module) encode the standard procedures — prefer them.",
        "K006",
        "new-model, new-page, add-module, new-module",
    ),
    (
        "AGENTS.md",
        "`make up` — start the stack; `make migrate` — makemigrations + migrate",
        "K007",
        "`make migrate` runs makemigrations + migrate",
    ),
    (
        "AGENTS.md",
        "`karni types` — regenerate TS types + typed hooks from the API schema",
        "K007",
        "regenerates ts types + typed hooks",
    ),
    (
        "AGENTS.md",
        "`karni check` — architecture and system checks; `karni context` — inventory",
        "K007",
        "architecture and system checks",
    ),
    ("CLAUDE.md", "@AGENTS.md", "adapter:CLAUDE.md", "@agents.md"),
    (
        ".cursorrules",
        "before any work and follow it exactly",
        "adapter:.cursor/rules/karni.mdc",
        "before any work",
    ),
    (
        ".claude/commands/new-model.md",
        "Do NOT write an admin, serializer or router.",
        "procedure:new-model",
        "do not write an admin, serializer or router",
    ),
    (
        ".claude/commands/new-model.md",
        "The auto-router registers it",
        "procedure:new-model",
        "the auto-router registers it",
    ),
    (
        ".claude/commands/new-model.md",
        "Total new code should be well under 20 lines.",
        "procedure:new-model",
        "well under 20 lines",
    ),
    (
        ".claude/commands/new-model.md",
        "GET /api/<plural>/ works.",
        "procedure:new-model",
        "get /api/<plural>/ works",
    ),
    (
        ".claude/commands/new-page.md",
        "never\n   hand-roll tables, forms or fetching",
        "procedure:new-page",
        "never hand-roll tables, forms or fetching",
    ),
    (
        ".claude/commands/new-page.md",
        "(`columns`, `fields`, `rowActions`,",
        "procedure:new-page",
        "`rowactions`",
    ),
    (
        ".claude/commands/new-page.md",
        "Register the route alongside the existing pages.",
        "procedure:new-page",
        "register the route alongside the existing pages",
    ),
    (
        ".claude/commands/new-page.md",
        "(`useResourceList`, `useResourceItem`, `useResourceMutations`",
        "procedure:new-page",
        "`useresourcemutations`",
    ),
    (
        ".claude/commands/add-module.md",
        "wires `karni_<module>` into the INSTALLED_APPS block",
        "procedure:add-module",
        "wires `karni_<module>` into the installed_apps block",
    ),
    (
        ".claude/commands/add-module.md",
        "Rebuild/install: `docker compose build`",
        "procedure:add-module",
        "`docker compose build`",
    ),
    (
        ".claude/commands/add-module.md",
        "the module must appear under MODULES.",
        "procedure:add-module",
        "must appear under modules",
    ),
    (
        ".claude/commands/add-module.md",
        "do not patch its internals.",
        "K308",
        "never patch its internals",
    ),
    (
        ".claude/commands/new-module.md",
        "confirm the domain isn't already covered.",
        "procedure:new-module",
        "confirm the domain isn't already covered",
    ),
    (
        ".claude/commands/new-module.md",
        "No admin.py, serializers.py, urls.py, forms.py",
        "procedure:new-module",
        "no admin.py, serializers.py, urls.py, forms.py",
    ),
    (
        ".claude/commands/new-module.md",
        "say so instead of building it.",
        "K307",
        "say so instead of building it",
    ),
]


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


@pytest.mark.parametrize(("legacy", "statement", "target", "phrase"), COVERAGE)
def test_every_audited_statement_survives(
    legacy: str, statement: str, target: str, phrase: str, generated_project: Path
) -> None:
    assert _norm(statement) in _norm(LEGACY_FILES[legacy]), "coverage table is out of date"
    data = agent_data.load(None)
    if target.startswith("adapter:"):
        text = (generated_project / target.split(":", 1)[1]).read_text()
    elif target.startswith("procedure:"):
        procedure = data.procedure(target.split(":", 1)[1])
        assert procedure is not None
        text = render_procedure(procedure)
    else:
        rule = data.rule(target)
        assert rule is not None, target
        text = rule["rule"]
    assert phrase in _norm(text), (target, phrase)


def test_coverage_table_spans_every_legacy_file() -> None:
    assert {legacy for legacy, *_ in COVERAGE} == set(LEGACY_FILES)


def test_sync_function_reports_without_cli(generated_project: Path) -> None:
    result = sync(generated_project, agent_data.load(generated_project), check=True)
    assert result.stale == []
    assert len(result.unchanged) == len(ADAPTER_FILES | COMMAND_FILES)

"""The module catalog: manifests, karni modules list/show, karni add from the manifest,
karni remove, the spec validator reading the catalog, and the CATALOG lines of karni context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from karni_cli import catalog
from karni_cli.commands import context as context_cmd
from karni_cli.commands import remove as remove_command
from karni_cli.main import app
from karni_cli.spec import catalog as spec_catalog
from karni_cli.spec import plan as plan_mod
from karni_cli.spec import schema
from karni_cli.spec.validate import validate_text

from .conftest import REPO_ROOT

#: Tokens the CATALOG block of karni context may take with Karni's 6 modules and 6 features
#: (with karni-charts, karni-reports and the user_grants line).
CATALOG_TOKEN_BUDGET = 320

CHAT = """
name = "chat"
kind = "module"
title = "Chat"
purpose = "Rooms and messages."
status = "experimental"
use_when = ["chat"]
requires = ["payments"]

[provides]
models = ["Room"]
settings = { KARNI_CHAT_ROOMS = "integer" }

[[asks]]
question = "How many rooms?"
setting = "KARNI_CHAT_ROOMS"
default = 3

[wiring]
apps = ["karni_chat"]
"""


@pytest.fixture
def no_docker() -> None:
    """The suite never asks docker (conftest's _no_compose_lookup): named for readability."""


@pytest.fixture
def project_venv(generated_project: Path) -> Path:
    """A fake project .venv python, so the guidance is read through "the project interpreter"."""
    python = generated_project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    return python


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _code(result: Any) -> str | None:
    """The code of the CliError a command raised (``karni`` prints it, the runner keeps it)."""
    return getattr(result.exception, "code", None)


def _module(text: str, name: str = "third party") -> Any:
    return catalog.parse_text(text, name)


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch) -> list[list[dict[str, Any]]]:
    """``manage.py karni_rows`` answering that no table exists; records each request."""
    asked: list[list[dict[str, Any]]] = []

    def count(requests: list[dict[str, Any]]) -> dict[str, Any]:
        asked.append(requests)
        return {"rows": [None] * len(requests), "unreachable": {}}

    monkeypatch.setattr(remove_command, "_default_counter", lambda project: count)
    return asked


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Manifests the project's interpreter reports as installed (a third-party module)."""
    found: list[Any] = []
    monkeypatch.setattr(catalog, "project_installed", lambda project: (list(found), []))
    return found


# manifests ---------------------------------------------------------------------------


def test_every_manifest_in_the_repo_is_valid() -> None:
    loaded = catalog.load()
    assert loaded.problems == []
    assert [m.name for m in loaded.modules] == [
        "approvals",
        "charts",
        "impersonation",
        "payments",
        "reports",
        "site",
    ]
    assert [m.name for m in loaded.features] == [
        "api_cache",
        "email_code_login",
        "social_login",
        "terms",
        "two_factor",
        "user_grants",
    ]
    for manifest in loaded.modules:
        path = REPO_ROOT / "modules" / f"karni-{manifest.name}" / f"karni_{manifest.name}"
        assert Path(manifest.source) == path / "karni.module.toml"
        assert manifest.app == f"karni_{manifest.name}"


def test_the_bundled_copy_serves_without_the_monorepo(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    bundle = Path(catalog.__file__).parent / "_catalog"
    if not (bundle / "modules").is_dir():
        pytest.skip("the build hook has not bundled the catalog into this checkout")
    monkeypatch.setattr(catalog, "_source_root", lambda: None)
    monkeypatch.delitem(sys.modules, catalog._MODULE_NAME, raising=False)
    catalog._bundled.cache_clear()
    try:
        loaded = catalog.load()
        payments = loaded.get("payments")
        assert payments is not None and "_catalog" in payments.source
        source = Path(__file__).resolve().parents[2] / "karni" / "karni" / "catalog" / "features"
        # A stale bundle (karni-cli installed before a feature was added) fails here: reinstall.
        assert len(loaded.features) == len(list(source.glob("*.toml"))) and loaded.problems == []
    finally:
        catalog._bundled.cache_clear()
        sys.modules.pop(catalog._MODULE_NAME, None)


def test_an_invalid_manifest_fails_with_every_problem() -> None:
    from karni_cli.project import CliError

    with pytest.raises(CliError) as caught:
        catalog.parse_text(CHAT.replace('kind = "module"', 'kind = "module"\ncolour = "red"'), "x")
    assert caught.value.code == "C314" and "unknown key 'colour'" in caught.value.message


def test_the_spec_reads_modules_and_features_from_the_catalog() -> None:
    loaded = catalog.load()
    assert set(spec_catalog.MODULES) == {m.name for m in loaded.modules}
    assert spec_catalog.MODULES["payments"].models == ("Payment", "Refund", "WebhookEvent")
    assert spec_catalog.MODULES["payments"].options["provider"] == ("string",)
    assert "secret_key" not in spec_catalog.MODULES["payments"].options  # credentials
    features = {m.name: m.switch for m in loaded.features if m.in_spec}
    assert {name: f.switch for name, f in spec_catalog.FEATURES.items()} == features
    # the schema's features: and karni plan's settings follow the catalog
    assert set(schema.Features.model_fields) == set(features)
    assert plan_mod._FEATURE_SETTINGS == features


def test_social_providers_come_from_the_manifest() -> None:
    from karni.accounts.social_token import BUILTIN_PROVIDERS

    assert spec_catalog.SOCIAL_PROVIDERS == ("google", "microsoft", "apple")
    assert set(spec_catalog.SOCIAL_PROVIDERS) == set(BUILTIN_PROVIDERS)


def test_the_site_wiring_matches_karni_make_site() -> None:
    from karni_cli.generators import site

    manifest = catalog.load().get("site")
    assert manifest is not None
    assert [(e.path, e.why) for e in manifest.wiring.middleware] == [
        (site.REDIRECT_MIDDLEWARE, site.REDIRECT_WHY)
    ]
    assert [(e.path, e.why) for e in manifest.wiring.context_processors] == [
        (site.SITE_PROCESSOR, site.PROCESSOR_WHY)
    ]
    assert f"# --- {manifest.title} ({manifest.distribution})" == site.PROCESSORS_HEADING


# the spec validator reads the catalog -------------------------------------------------


def _codes(text: str) -> list[str]:
    return [issue.code for issue in validate_text(text).issues]


def test_a_module_of_the_catalog_is_valid_in_a_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = "version: 1\napp: {name: Shop}\nmodules:\n  chat: {rooms: 5}\n  payments: {}\n"
    assert _codes(spec) == ["C236"]
    monkeypatch.setitem(spec_catalog.MODULES, "chat", spec_catalog.known_module(_module(CHAT)))
    assert _codes(spec) == []
    assert _codes(spec.replace("rooms: 5", "seats: 5")) == ["C221"]
    assert _codes(spec.replace("rooms: 5", "rooms: lots")) == ["C221"]


def test_the_spec_checks_requires_and_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(spec_catalog.MODULES, "chat", spec_catalog.known_module(_module(CHAT)))
    alone = "version: 1\napp: {name: Shop}\nmodules:\n  chat: {}\n"
    [issue] = validate_text(alone).issues
    assert issue.code == "C324" and "chat requires payments" in issue.message
    assert _codes(alone + "  payments: {}\n") == []
    rival = _module(CHAT.replace("requires", "conflicts"))
    monkeypatch.setitem(spec_catalog.MODULES, "chat", spec_catalog.known_module(rival))
    both = alone + "  payments: {}\nfeatures: {two_factor: true}\n"
    [issue] = validate_text(both).issues
    assert issue.code == "C324" and "cannot be used together" in issue.message


# karni modules list / show -------------------------------------------------------------


def test_list_outside_a_project(runner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["modules", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any(line.startswith("payments ") and "available" in line for line in lines)
    assert any(line.startswith("two_factor ") and "built in" in line for line in lines)
    assert "  ? Which payment provider: Stripe or Razorpay? -> KARNI_PAYMENTS_PROVIDER" in (
        result.output
    )
    data = json.loads(runner.invoke(app, ["modules", "list", "--json"]).output)
    states = {entry["name"]: entry["state"] for entry in data["entries"]}
    assert states["payments"] == "available" and states["terms"] == "built in"
    payments = next(e for e in data["entries"] if e["name"] == "payments")
    assert payments["wiring"]["urls"] == 'path("payments/", include("karni_payments.urls"))'
    assert payments["asks"][0]["options"] == ["stripe", "razorpay", "test"]


def test_list_and_show_in_a_project(
    runner, generated_project: Path, monkeypatch, installed: list[Any]
) -> None:
    monkeypatch.chdir(generated_project)
    assert runner.invoke(app, ["add", "payments"]).exit_code == 0
    installed.append(_module(CHAT, "entry point chat"))
    data = json.loads(runner.invoke(app, ["modules", "list", "--json"]).output)
    states = {entry["name"]: entry["state"] for entry in data["entries"]}
    assert states["payments"] == "added"  # in the # karni:apps block
    assert states["chat"] == "installed"  # the project's interpreter has it, not added
    assert states["approvals"] == "available"

    shown = runner.invoke(app, ["modules", "show", "payments"])
    assert shown.exit_code == 0, shown.output
    assert shown.output.startswith("payments: Payments (module, stable, added)")
    assert "Which currency, as a lowercase ISO 4217 code? -> KARNI_PAYMENTS_CURRENCY" in (
        shown.output
    )
    assert "  INSTALLED_APPS: karni_payments" in shown.output
    feature = runner.invoke(app, ["modules", "show", "two_factor"])
    assert "Turn on: KARNI_2FA, or features: two_factor in karni.yaml. Needs karni[2fa]." in (
        feature.output
    )
    as_json = json.loads(runner.invoke(app, ["modules", "show", "chat", "--json"]).output)
    assert as_json["requires"] == ["payments"] and as_json["state"] == "installed"
    assert _code(runner.invoke(app, ["modules", "show", "nope"])) == "C313"


# karni add / karni remove ---------------------------------------------------------------


@pytest.mark.parametrize(
    "module", ["payments", "approvals", "impersonation", "site", "charts", "reports"]
)
def test_add_then_remove_gives_the_files_back(
    runner, generated_project: Path, monkeypatch, no_docker, counter, module: str
) -> None:
    monkeypatch.chdir(generated_project)
    before = _snapshot(generated_project)
    added = runner.invoke(app, ["add", module])
    assert added.exit_code == 0, added.output
    assert _snapshot(generated_project) != before
    removed = runner.invoke(app, ["remove", module])
    assert removed.exit_code == 0, removed.output
    assert _snapshot(generated_project) == before
    assert f"uv pip uninstall karni-{module}" in removed.output
    [requests] = counter  # the module's models, counted before it was unwired
    manifest = catalog.load().get(module)
    assert manifest is not None
    assert requests == [{"model": f"karni_{module}.{model}"} for model in manifest.provides.models]


def test_remove_takes_out_a_recorded_fragment_and_the_include(
    runner, generated_project: Path, monkeypatch, no_docker, counter, project_venv: Path
) -> None:
    import subprocess

    from karni_cli.commands import add as add_command

    monkeypatch.chdir(generated_project)
    project_venv.unlink()
    before = _snapshot(generated_project)
    project_venv.write_text("#!/bin/sh\n")

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="## Payments\n- hi\n", stderr="")

    monkeypatch.setattr(add_command.subprocess, "run", fake_run)
    monkeypatch.setattr(catalog, "project_installed", lambda project: None)
    assert runner.invoke(app, ["add", "payments"]).exit_code == 0
    assert (generated_project / ".karni" / "modules" / "payments.md").is_file()
    urls = generated_project / "config" / "urls.py"
    urls.write_text(
        urls.read_text().replace(
            "    # karni:urls\n",
            '    path("payments/", include("karni_payments.urls")),\n    # karni:urls\n',
        )
    )
    dry = runner.invoke(app, ["remove", "payments", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "config/urls.py: the include of karni_payments.urls removed" in dry.output
    assert "karni_payments" in urls.read_text()  # --dry-run wrote nothing
    project_venv.unlink()  # the venv is fake: the generated files must not change by it
    result = runner.invoke(app, ["remove", "payments"])
    assert result.exit_code == 0, result.output
    after = _snapshot(generated_project)
    assert {k: v for k, v in after.items() if k != ".venv/bin/python"} == before
    assert "karni:module:payments" not in (generated_project / "AGENTS.md").read_text()


def test_remove_reports_rows_and_drops_nothing(
    runner, generated_project: Path, monkeypatch, no_docker
) -> None:
    def count(requests: list[dict[str, Any]]) -> dict[str, Any]:
        return {"rows": [12, 0, None], "unreachable": {}}

    monkeypatch.setattr(remove_command, "_default_counter", lambda project: count)
    monkeypatch.chdir(generated_project)
    assert runner.invoke(app, ["add", "payments"]).exit_code == 0
    added = _snapshot(generated_project)

    refused = runner.invoke(app, ["remove", "payments"])
    assert refused.exit_code == 1 and _code(refused) == "C319"
    assert "  karni migrate karni_payments zero" in str(refused.exception)
    assert "  karni_payments_payment (karni_payments.Payment): 12 rows" in refused.output
    assert "  karni_payments_refund (karni_payments.Refund): 0 rows" in refused.output
    assert "  karni_payments_webhookevent (karni_payments.WebhookEvent): no table" in (
        refused.output
    )
    assert _snapshot(generated_project) == added  # nothing written

    dry = runner.invoke(app, ["remove", "payments", "--dry-run"])
    assert dry.exit_code == 0 and "would stop here (C319)" in dry.output

    kept = runner.invoke(app, ["remove", "payments", "--keep-tables"])
    assert kept.exit_code == 0, kept.output
    assert "12 rows" in kept.output and "Its tables stay in the database" in kept.output
    assert '"karni_payments"' not in (generated_project / "config" / "settings.py").read_text()


def test_remove_refuses_while_another_module_requires_it(
    runner, generated_project: Path, monkeypatch, no_docker, counter, installed: list[Any]
) -> None:
    monkeypatch.chdir(generated_project)
    installed.append(_module(CHAT, "entry point chat"))
    assert runner.invoke(app, ["add", "payments"]).exit_code == 0
    chat = runner.invoke(app, ["add", "chat"])
    assert chat.exit_code == 0, chat.output
    assert '"karni_chat",' in (generated_project / "config" / "settings.py").read_text()
    refused = runner.invoke(app, ["remove", "payments"])
    assert _code(refused) == "C316" and "chat requires" in str(refused.exception)
    assert runner.invoke(app, ["remove", "chat"]).exit_code == 0
    assert runner.invoke(app, ["remove", "payments"]).exit_code == 0


def test_add_refuses_a_conflict(
    runner, generated_project: Path, monkeypatch, no_docker, installed: list[Any]
) -> None:
    monkeypatch.chdir(generated_project)
    installed.append(_module(CHAT.replace("requires", "conflicts"), "entry point chat"))
    assert runner.invoke(app, ["add", "payments"]).exit_code == 0
    before = _snapshot(generated_project)
    refused = runner.invoke(app, ["add", "chat"])
    assert _code(refused) == "C315"
    assert _snapshot(generated_project) == before


def test_remove_refuses_a_feature_and_a_module_not_added(
    runner, generated_project: Path, monkeypatch, no_docker, counter
) -> None:
    monkeypatch.chdir(generated_project)
    feature = runner.invoke(app, ["remove", "two_factor"])
    assert _code(feature) == "C318"
    assert _code(runner.invoke(app, ["remove", "approvals"])) == "C317"
    assert _code(runner.invoke(app, ["add", "two_factor"])) == "C318"


def test_add_prints_what_the_manifest_says(
    runner, generated_project: Path, monkeypatch, no_docker
) -> None:
    monkeypatch.chdir(generated_project)
    payments = runner.invoke(app, ["add", "payments"])
    assert "Extras, e.g. karni-payments[stripe]: stripe (the Stripe provider)" in payments.output
    assert "It needs a Celery worker: webhook state changes run as tasks." in payments.output
    assert "Its options and questions: karni modules show payments" in payments.output
    approvals = runner.invoke(app, ["add", "approvals"])
    assert "include(" not in approvals.output  # no URLs: no include line
    impersonation = runner.invoke(app, ["add", "impersonation"])
    assert (
        "Add 'karni_impersonation.middleware.ImpersonationMiddleware' to MIDDLEWARE"
        in impersonation.output
    )
    settings = (generated_project / "config" / "settings.py").read_text()
    assert "ImpersonationMiddleware" not in settings  # printed, as karni add always did


def test_a_module_without_a_manifest_is_added_and_removed_by_convention(
    runner, generated_project: Path, monkeypatch, no_docker, counter
) -> None:
    monkeypatch.chdir(generated_project)
    before = _snapshot(generated_project)
    added = runner.invoke(app, ["add", "widgets"])
    assert added.exit_code == 0, added.output
    assert 'path("widgets/", include("karni_widgets.urls"))' in added.output
    assert runner.invoke(app, ["remove", "widgets"]).exit_code == 0
    assert _snapshot(generated_project) == before
    assert counter == []  # no manifest, no models to count


# karni context ------------------------------------------------------------------------


def test_the_catalog_in_karni_context(runner, generated_project: Path, monkeypatch) -> None:
    monkeypatch.chdir(generated_project)
    lines = context_cmd.catalog_lines(generated_project, "MODULES: \nFEATURES: two_factor")
    loaded = catalog.load()
    assert len(lines) == 1 + len(loaded.entries)
    assert "  payments module, not added: " in "\n".join(lines)
    assert "  two_factor feature, on: " in "\n".join(lines)
    assert "  terms feature, off: " in "\n".join(lines)
    older = context_cmd.catalog_lines(generated_project, "MODULES: ")  # a karni without FEATURES
    assert "  terms feature: " in "\n".join(older)
    settings = generated_project / "config" / "settings.py"
    settings.write_text(settings.read_text().replace('    # "myapp",\n', '    "karni_payments",\n'))
    assert "  payments module, added: " in "\n".join(context_cmd.catalog_lines(generated_project))


def test_the_catalog_fits_its_token_budget(generated_project: Path) -> None:
    text = "\n".join(context_cmd.catalog_lines(generated_project, "FEATURES: none"))
    assert len(text) / 4 < CATALOG_TOKEN_BUDGET
    tiktoken = pytest.importorskip("tiktoken")
    for name in ("cl100k_base", "o200k_base"):
        try:
            encoding = tiktoken.get_encoding(name)
        except Exception:  # noqa: BLE001 - encodings download on first use
            pytest.skip("tiktoken encodings unavailable offline")
        assert len(encoding.encode(text)) < CATALOG_TOKEN_BUDGET, name


def test_the_rules_point_at_the_catalog() -> None:
    from karni_cli import agent_data

    data = agent_data.load(None)
    rule = data.rule("K307")
    assert rule is not None and "karni modules list" in rule["summary"]
    procedure = data.procedure("add-module")
    assert procedure is not None
    steps = " ".join(procedure["steps"])
    assert "karni modules show <module>" in steps and "karni remove <module>" in steps


def test_remove_takes_out_a_hand_wired_middleware(
    runner, generated_project: Path, monkeypatch, no_docker, counter
) -> None:
    monkeypatch.chdir(generated_project)
    before = _snapshot(generated_project)
    assert runner.invoke(app, ["add", "impersonation"]).exit_code == 0
    settings = generated_project / "config" / "settings.py"
    settings.write_text(
        settings.read_text().replace(
            "]  # karni:middleware",
            '    "karni_impersonation.middleware.ImpersonationMiddleware",\n]  # karni:middleware',
        )
    )
    result = runner.invoke(app, ["remove", "impersonation"])
    assert result.exit_code == 0, result.output
    assert "ImpersonationMiddleware out of MIDDLEWARE" in result.output
    assert _snapshot(generated_project) == before

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from karni_cli import project as project_mod
from karni_cli.commands.context import (
    apps_line,
    assemble,
    catalog_lines,
    find_manifest,
    manifest_lines,
    pages_line,
    site_line,
    with_catalog,
)
from karni_cli.main import app

BACKEND = (
    "MODELS: Event(title,starts_at,capacity,status) Venue(name,address)\n"
    "VIEWSETS: EventViewSet VenueViewSet\n"
    "MODULES: payments\n"
    "BASES: BaseModel SoftDeleteModel BaseViewSet KarniModelAdmin AbstractKarniUser"
)


def _top_level(output: str) -> list[str]:
    """The inventory's ``KEY:`` lines (the CATALOG block's entries are indented)."""
    return [line for line in output.strip().split("\n") if not line.startswith(" ")]


def test_assemble_orders_sections() -> None:
    out = assemble(BACKEND, ["COMPONENTS: Page ResourceTable", "HOOKS: useAuth"])
    lines = out.split("\n")
    assert [line.split(":")[0] for line in lines] == [
        "MODELS",
        "VIEWSETS",
        "COMPONENTS",
        "HOOKS",
        "MODULES",
        "BASES",
    ]


def test_assemble_without_manifest_omits_ui_lines() -> None:
    out = assemble(BACKEND, [])
    assert "COMPONENTS" not in out and "HOOKS" not in out


def test_manifest_lines(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"components": ["ResourceTable", "Page"], "hooks": ["useAuth"]}))
    assert manifest_lines(manifest) == [
        "COMPONENTS: Page ResourceTable",
        "HOOKS: useAuth",
    ]


def test_find_manifest_prefers_frontend(tmp_path: Path) -> None:
    target = tmp_path / "frontend" / "node_modules" / "@karni" / "ui" / "dist" / "manifest.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}")
    assert find_manifest(tmp_path, None) == target
    assert find_manifest(tmp_path, tmp_path / "nope.json") is None


def test_cli_end_to_end_with_mocked_backend(runner, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=BACKEND + "\n", stderr=""),
    )
    result = runner.invoke(app, ["context"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == with_catalog(BACKEND, catalog_lines(tmp_path, BACKEND))


def test_budget_for_ten_model_project() -> None:
    models = " ".join(f"Model{i}(alpha,beta,gamma,delta)" for i in range(10))
    output = assemble(
        f"MODELS: {models}\nVIEWSETS: "
        + " ".join(f"Model{i}ViewSet" for i in range(10))
        + "\nBASES: BaseModel SoftDeleteModel BaseViewSet KarniModelAdmin AbstractKarniUser",
        [],
    )
    assert len(output) < 800


def test_apps_and_pages_are_read_statically(generated_project: Path) -> None:
    settings = generated_project / "config" / "settings.py"
    settings.write_text(
        settings.read_text().replace(
            '    # "myapp",\n',
            '    # "commented",\n    "events",\n    "apps.billing.apps.BillingConfig",\n'
            '    "karni_payments",\n',
        )
    )
    (generated_project / "events").mkdir()
    (generated_project / "apps" / "billing").mkdir(parents=True)
    assert apps_line(generated_project) == "APPS: events(events/) billing(apps/billing/)"

    pages = generated_project / "frontend" / "src" / "pages"
    (pages / "events").mkdir(parents=True)
    (pages / "home.tsx").write_text("")
    (pages / "events" / "edit.tsx").write_text("")
    (pages / "home.test.tsx").write_text("")
    assert pages_line(generated_project) == "PAGES: events/edit home"


def test_context_prepends_apps_and_appends_pages(
    runner, generated_project: Path, monkeypatch
) -> None:
    settings = generated_project / "config" / "settings.py"
    settings.write_text(settings.read_text().replace('    # "myapp",\n', '    "events",\n'))
    (generated_project / "events").mkdir()
    # The scaffold ships frontend/src/pages/ (home.tsx) already.
    (generated_project / "frontend" / "src" / "pages").mkdir(parents=True, exist_ok=True)
    (generated_project / "frontend" / "src" / "pages" / "events.tsx").write_text("")
    monkeypatch.chdir(generated_project)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=BACKEND + "\n", stderr=""),
    )
    result = runner.invoke(app, ["context"])
    assert result.exit_code == 0, result.output
    keys = [line.split(":")[0] for line in _top_level(result.output)]
    assert keys == ["KIND", "APPS", "MODELS", "VIEWSETS", "PAGES", "MODULES", "CATALOG", "BASES"]


def test_context_failure_exits_nonzero(runner, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 3, stdout="", stderr="boom\n"),
    )
    assert runner.invoke(app, ["context"]).exit_code == 1


def test_site_routes_are_read_statically(generated_project: Path) -> None:
    assert site_line(generated_project) is None  # karni.* includes are not the project's
    config = generated_project / "config" / "urls.py"
    config.write_text(
        config.read_text().replace(
            "    # karni:urls\n",
            '    path("hooks/", include("billing.urls")),\n'
            '    path("", include("website.urls")),\n'
            "    # karni:urls\n",
        )
    )
    (generated_project / "website").mkdir()
    (generated_project / "website" / "urls.py").write_text(
        "urlpatterns = [\n"
        '    path("", views.home, name="home"),\n'
        '    path("services/<slug:slug>/", views.service, name="service"),\n'
        "]\n"
    )
    (generated_project / "billing").mkdir()
    (generated_project / "billing" / "urls.py").write_text(
        'urlpatterns = [path("stripe/", views.stripe)]\n'
    )
    assert site_line(generated_project) == (
        "SITE: billing(/hooks/stripe/) website(/ /services/<slug:slug>/)"
    )


def test_context_lists_the_site_after_the_pages(
    runner, generated_project: Path, monkeypatch
) -> None:
    config = generated_project / "config" / "urls.py"
    config.write_text(
        config.read_text().replace(
            "    # karni:urls\n", '    path("", include("website.urls")),\n    # karni:urls\n'
        )
    )
    (generated_project / "website").mkdir()
    (generated_project / "website" / "urls.py").write_text(
        'urlpatterns = [path("", views.home, name="home")]\n'
    )
    monkeypatch.chdir(generated_project)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=BACKEND + "\n", stderr=""),
    )
    result = runner.invoke(app, ["context"])
    assert result.exit_code == 0, result.output
    lines = _top_level(result.output)
    assert [line.split(":")[0] for line in lines][-5:] == [
        "PAGES",
        "SITE",
        "MODULES",
        "CATALOG",
        "BASES",
    ]
    assert "SITE: website(/)" in lines


def test_routes_read_calls_that_span_lines() -> None:
    """ruff format splits a long path() call: its name is still its own."""
    from karni_cli.urls_edit import add_route, routes

    text = (
        "urlpatterns = [\n"
        '    path("", views.home, name="home"),\n'
        "    path(\n"
        '        "specials/",\n'
        "        RedirectView.as_view(\n"
        '            pattern_name="website:menu", permanent=True, query_string=True\n'
        "        ),\n"
        '        name="specials",\n'
        "    ),\n"
        '    # path("old/", views.old, name="old"),\n'
        '    path("menu/", views.menu, name="menu"),  # the (menu)\n'
        "    # karni:urls\n"
        "]\n"
    )
    assert routes(text) == [
        ("", "home", None),
        ("specials/", "specials", None),
        ("menu/", "menu", None),
    ]
    entry = 'path(\n    "a/",\n    views.a,\n    name="a",\n),'
    added = add_route(text, entry, filename="urls.py", manual="")
    assert added is not None
    assert (
        '    path(\n        "a/",\n        views.a,\n        name="a",\n    ),\n    # karni:urls'
        in added
    )
    assert add_route(added, entry, filename="urls.py", manual="") is None


# slices (experimental): --summary, --app, --model, --max-tokens

SUMMARY = (
    "SUMMARY: 2 apps, 3 models, 2 viewsets. One app: karni context --app <label>. One model: "
    "karni context --model <name>.\n"
    "APP catalog: 2 models (Category Product), 2 viewsets, 3 pages\n"
    "APP regions: 1 model (Region), 0 viewsets, 0 pages"
)
APP_SLICE = (
    "MODELS: Category(name,parent) Product(name,sku,price,category)\n"
    "KEYS: uuid(all)\n"
    "RELATIONS: Category.parent->Category Product.category->Category\n"
    "VIEWSETS: ProductViewSet(products read=Public() write=HasRole('staff'))\n"
    "PAGES: products product-detail\n"
    "BASES: BaseModel BaseViewSet"
)
MODEL_SLICE = (
    "MODEL: catalog.Product (catalog/models.py:12) key uuid, table catalog_product\n"
    "FIELDS: name str:200, sku str:40 unique, price decimal:10,2, category fk:Category\n"
    "VIEWSETS: ProductViewSet(products read=Public() write=HasRole('staff') search=name)"
)


def _slice_project(tmp_path: Path, monkeypatch, outputs: dict[str, str]) -> list[list[str]]:
    """A project whose backend answers each argv with ``outputs[flag]``; the argvs it got."""
    (tmp_path / "manage.py").write_text("")
    (tmp_path / "config").mkdir()
    (tmp_path / "catalog").mkdir()
    (tmp_path / "regions").mkdir()
    (tmp_path / "config" / "settings.py").write_text(
        'INSTALLED_APPS = [\n    "catalog",\n    "regions",\n    # karni:apps\n]\n'
    )
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []

    def run_manage(project: Path, args: list[str], **kwargs: object) -> object:
        calls.append(list(args))
        flag = next((arg for arg in args if arg.startswith("--")), "")
        return subprocess.CompletedProcess(args, 0, stdout=outputs.get(flag, BACKEND) + "\n")

    monkeypatch.setattr(project_mod, "run_manage", run_manage)
    return calls


def test_the_default_output_is_unchanged_by_the_slices(runner, tmp_path: Path, monkeypatch) -> None:
    calls = _slice_project(tmp_path, monkeypatch, {})
    result = runner.invoke(app, ["context"])
    assert result.exit_code == 0, result.output
    assert calls == [["karni_context"]]
    expected = with_catalog(BACKEND, catalog_lines(tmp_path, BACKEND))
    assert result.output.strip() == "APPS: catalog(catalog/) regions(regions/)\n" + expected
    # --max-tokens large enough changes nothing either
    again = runner.invoke(app, ["context", "--max-tokens", "100000"])
    assert again.output == result.output


def test_summary_is_one_line_per_app(runner, tmp_path: Path, monkeypatch) -> None:
    calls = _slice_project(tmp_path, monkeypatch, {"--summary": SUMMARY})
    result = runner.invoke(app, ["context", "--summary"])
    assert result.exit_code == 0, result.output
    assert calls == [["karni_context", "--summary"]]
    lines = result.output.strip().split("\n")
    assert lines[0] == "APPS: catalog(catalog/) regions(regions/)"
    assert lines[1].startswith("SUMMARY: 2 apps")
    assert lines[2:] == SUMMARY.split("\n")[1:]
    assert "CATALOG" not in result.output and "BASES" not in result.output


def test_app_slice_names_only_that_app(runner, tmp_path: Path, monkeypatch) -> None:
    calls = _slice_project(tmp_path, monkeypatch, {"--app": APP_SLICE})
    result = runner.invoke(app, ["context", "--app", "catalog"])
    assert result.exit_code == 0, result.output
    assert calls == [["karni_context", "--app", "catalog"]]
    assert result.output.strip() == "APPS: catalog(catalog/)\n" + APP_SLICE


def test_model_slice_is_repeatable(runner, tmp_path: Path, monkeypatch) -> None:
    calls = _slice_project(tmp_path, monkeypatch, {"--model": MODEL_SLICE})
    result = runner.invoke(app, ["context", "--model", "Product", "--model", "regions.Region"])
    assert result.exit_code == 0, result.output
    assert calls == [["karni_context", "--model", "Product", "--model", "regions.Region"]]
    assert result.output.strip() == MODEL_SLICE  # no APPS line for a model slice


def test_summary_and_model_do_not_combine(runner, tmp_path: Path, monkeypatch) -> None:
    _slice_project(tmp_path, monkeypatch, {})
    result = runner.invoke(app, ["context", "--summary", "--model", "Product"])
    assert result.exit_code == 2 and "--summary" in result.output


def test_max_tokens_cuts_at_whole_sections_and_names_the_rest(
    runner, tmp_path: Path, monkeypatch
) -> None:
    _slice_project(tmp_path, monkeypatch, {"--app": APP_SLICE})
    result = runner.invoke(app, ["context", "--app", "catalog", "--max-tokens", "60"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().split("\n")
    assert lines[:3] == ["APPS: catalog(catalog/)", *APP_SLICE.split("\n")[:2]]
    assert lines[-1].startswith("LEFT OUT: RELATIONS VIEWSETS PAGES BASES (~")
    assert lines[-1].endswith("tokens). karni context --app catalog prints them.")
    assert len(result.output.strip()) <= 60 * 4


def test_cut_sections_keeps_indented_lines_with_their_section() -> None:
    from karni_cli.commands.context import cut_sections, estimate_tokens, split_sections

    catalog = "CATALOG: modules\n" + "\n".join(f"  module{i}, added: purpose" for i in range(9))
    text = f"KIND: app\n{catalog}\nBASES: x"
    assert split_sections(text) == ["KIND: app", catalog, "BASES: x"]
    assert cut_sections(text, 1000, "karni context") == text
    cut = cut_sections(text, 40, "karni context")
    assert cut.startswith("KIND: app\nLEFT OUT: CATALOG BASES")
    assert estimate_tokens(cut) <= 40
    # not even the first section fits: only the note
    assert cut_sections(text, 1, "karni context").startswith("LEFT OUT: KIND CATALOG BASES")


def test_a_karni_without_slices_is_named(runner, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 2, stdout="", stderr="manage.py karni_context: error: unrecognized arguments\n"
        ),
    )
    result = runner.invoke(app, ["context", "--summary"])
    assert result.exit_code == 1 and "C580" in result.output

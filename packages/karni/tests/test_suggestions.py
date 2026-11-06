"""karni.suggestions: each detector positive and negative, silencing, the setting, exit codes."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.management import call_command
from django.db import models
from django.test.utils import isolate_apps, override_settings

from karni import catalog, suggestions
from karni.fields import MarkdownField
from karni.models import BaseModel, TreeModel
from karni.testing import _source


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Point project discovery at ``tmp_path``: ``install(models)`` or ``install(app_dir)``."""
    monkeypatch.setattr(suggestions, "_root", lambda: tmp_path)

    def install(models_: list[Any] | None = None, app_dir: Path | None = None) -> None:
        cfg = SimpleNamespace(
            get_models=lambda: models_ or [],
            name="shopapp",
            label="shopapp",
            path=str(app_dir or tmp_path),
        )
        monkeypatch.setattr(_source, "project_app_configs", lambda: [cfg])
        _source._file_lines.cache_clear()

    return install


def codes(found: list[suggestions.Suggestion]) -> list[str]:
    return [item.code for item in found]


# SUG001 a tree written by hand


@isolate_apps("tests.testapp")
def test_a_self_foreign_key_named_like_a_parent_is_suggested(project: Any) -> None:
    class Category(BaseModel):  # noqa: DJ008
        category_parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    project([Category])
    (found,) = suggestions.suggest_tree_models()
    assert found.code == "SUG001"
    assert found.file.endswith("test_suggestions.py")
    assert found.line is not None
    assert "TreeModel" in found.fix and "Category.category_parent" in found.message


@isolate_apps("tests.testapp")
def test_the_tree_suggestion_leaves_what_the_rule_and_trees_cover(project: Any) -> None:
    class Folder(BaseModel):  # noqa: DJ008
        parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)  # the rule's

        class Meta:
            app_label = "testapp"

    class Person(BaseModel):  # noqa: DJ008
        manager = models.ForeignKey("self", null=True, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class Area(TreeModel, BaseModel):  # noqa: DJ008
        class Meta:
            app_label = "testapp"

    project([Folder, Person, Area])
    assert suggestions.suggest_tree_models() == []


@isolate_apps("tests.testapp")
def test_a_tree_suggestion_is_silenced_with_a_reason_only(project: Any) -> None:
    class Quiet(BaseModel):  # noqa: DJ008
        # karni: allow(suggest-tree-model): the rows are not a hierarchy
        category_parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class Loud(BaseModel):  # noqa: DJ008
        # karni: allow(suggest-tree-model):
        category_parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    project([Quiet])
    assert suggestions.suggest_tree_models() == []
    project([Loud])
    (found,) = suggestions.suggest_tree_models()
    assert "without a reason" in found.message


def test_markers_without_a_colon_and_several_on_a_line() -> None:
    """Area 1 F5 and F9: `allow(rule)` alone is a marker without a reason, and a second marker
    on the line is read."""
    assert suggestions.allows("x = 1  # karni: allow(suggest-markdown)") == [
        (["suggest-markdown"], "")
    ]
    line = "q()  # karni: allow(raw-sql): totals  # karni: allow(suggest-aggregate): one-off"
    assert suggestions.allows(line) == [
        (["raw-sql"], "totals"),
        (["suggest-aggregate"], "one-off"),
    ]
    assert suggestions.marker([line], "suggest-aggregate", [1]) == "silenced"
    assert suggestions.marker(["x  # karni: allow(suggest-markdown)"], "suggest-markdown", [1]) == (
        "no-reason"
    )


# SUG002 markdown in a text field


@isolate_apps("tests.testapp")
def test_markdown_in_a_text_field_is_suggested(project: Any) -> None:
    class Article(BaseModel):  # noqa: DJ008
        body_markdown = models.TextField()
        notes_md = models.TextField(blank=True)
        summary = models.TextField(help_text="Written in Markdown.")

        class Meta:
            app_label = "testapp"

    project([Article])
    found = suggestions.suggest_markdown_fields()
    assert codes(found) == ["SUG002"] * 3
    assert all("MarkdownField" in item.fix for item in found)
    assert len({item.line for item in found}) == 3


@isolate_apps("tests.testapp")
def test_other_text_is_not_suggested_as_markdown(project: Any) -> None:
    class Article(BaseModel):  # noqa: DJ008
        body_markdown = MarkdownField()
        description = models.TextField()
        slug_md = models.CharField(max_length=20)
        summary = models.TextField(help_text="Plain text, up to a paragraph.")

        class Meta:
            app_label = "testapp"

    project([Article])
    assert suggestions.suggest_markdown_fields() == []


@isolate_apps("tests.testapp")
def test_a_markdown_suggestion_is_silenced_with_a_reason(project: Any) -> None:
    class Article(BaseModel):  # noqa: DJ008
        body_markdown = models.TextField()  # karni: allow(suggest-markdown): imported as is

        class Meta:
            app_label = "testapp"

    project([Article])
    assert suggestions.suggest_markdown_fields() == []


# SUG003 grouped SQL by hand

GROUPED = """\
from django.db import connection


def by_region():
    with connection.cursor() as cur:
        cur.execute("SELECT region, COUNT(*) FROM shop_product GROUP BY region")  # {marker}
        return cur.fetchall()


def by_status():
    sql = "SELECT status, SUM(total) FROM shop_order group  by status"
    with connection.cursor() as cur:
        cur.execute(sql)  # {marker}
        return cur.fetchall()
"""


def write_sql(tmp_path: Path, marker: str, name: str = "reports.py") -> None:
    (tmp_path / name).write_text(GROUPED.format(marker=marker))


def test_raw_sql_opt_outs_with_group_by_suggest_the_aggregate(project: Any, tmp_path: Path) -> None:
    write_sql(tmp_path, "karni: allow(raw-sql): grouped counts")
    project()
    (found,) = suggestions.suggest_aggregate()
    assert found.code == "SUG003" and found.file == "reports.py" and found.line == 6
    assert "reports.py:6" in found.message and "reports.py:13" in found.message
    assert "aggregate" in found.fix


def test_the_aggregate_is_not_suggested_for_one_query_or_no_opt_out(
    project: Any, tmp_path: Path
) -> None:
    project()
    write_sql(tmp_path, "no marker here")
    assert suggestions.suggest_aggregate() == []  # not an opt-out: the raw-sql rule's
    (tmp_path / "one.py").write_text(
        'def f(cur):\n    cur.execute("SELECT a, COUNT(*) FROM t GROUP BY a")'
        "  # karni: allow(raw-sql): x\n"
    )
    (tmp_path / "plain.py").write_text(
        'def f(cur):\n    cur.execute("SELECT a FROM t")  # karni: allow(raw-sql): x\n'
        '    cur.execute("SELECT b FROM t")  # karni: allow(raw-sql): x\n'
    )
    (tmp_path / "reports.py").unlink(missing_ok=True)
    assert suggestions.suggest_aggregate() == []


def test_one_silenced_query_drops_the_aggregate_below_its_threshold(
    project: Any, tmp_path: Path
) -> None:
    project()
    write_sql(tmp_path, "karni: allow(raw-sql, suggest-aggregate): legacy report")
    assert suggestions.suggest_aggregate() == []


# SUG004 a taxonomy


def region_and_tagged(count: int) -> list[Any]:
    """A region tree and ``count`` models each with a many-to-many to it."""

    class Region(TreeModel, BaseModel):  # noqa: DJ008
        class Meta:
            app_label = "testapp"

    class Product(BaseModel):  # noqa: DJ008
        region = models.ManyToManyField(Region, blank=True, related_name="+")

        class Meta:
            app_label = "testapp"

    class Supplier(BaseModel):  # noqa: DJ008
        areas = models.ManyToManyField(Region, blank=True, related_name="+")

        class Meta:
            app_label = "testapp"

    class Article(BaseModel):  # noqa: DJ008
        # karni: allow(suggest-taxonomy): tagged by hand on purpose
        regions = models.ManyToManyField(Region, blank=True, related_name="+")

        class Meta:
            app_label = "testapp"

    return [Region, Product, Supplier, Article][: count + 1]


@isolate_apps("tests.testapp")
def test_three_models_tagged_to_one_tree_suggest_a_taxonomy(project: Any) -> None:
    class Region(TreeModel, BaseModel):  # noqa: DJ008
        class Meta:
            app_label = "testapp"

    class Product(BaseModel):  # noqa: DJ008
        region = models.ManyToManyField(Region, blank=True, related_name="+")

        class Meta:
            app_label = "testapp"

    class Supplier(BaseModel):  # noqa: DJ008
        areas = models.ManyToManyField(Region, blank=True, related_name="+")

        class Meta:
            app_label = "testapp"

    class Article(BaseModel):  # noqa: DJ008
        regions = models.ManyToManyField(Region, blank=True, related_name="+")

        class Meta:
            app_label = "testapp"

    project([Region, Product, Supplier, Article])
    (found,) = suggestions.suggest_taxonomies()
    assert found.code == "SUG004" and found.file.endswith("test_suggestions.py")
    assert "3 models" in found.message and "Region" in found.message
    assert "taxonomies" in found.fix and "testapp.Region" in found.fix


@isolate_apps("tests.testapp")
def test_two_tagged_models_suggest_nothing(project: Any) -> None:
    project(region_and_tagged(2))
    assert suggestions.suggest_taxonomies() == []


@isolate_apps("tests.testapp")
def test_a_silenced_model_leaves_two_and_suggests_nothing(project: Any) -> None:
    project(region_and_tagged(3))  # the third carries a marker with a reason
    assert suggestions.suggest_taxonomies() == []


@isolate_apps("tests.testapp")
def test_models_that_declare_the_taxonomy_suggest_nothing(project: Any) -> None:
    class Region(TreeModel, BaseModel):  # noqa: DJ008
        class Meta:
            app_label = "testapp"

    class One(BaseModel):  # noqa: DJ008
        region = models.ManyToManyField(Region, blank=True, related_name="+")

        class Karni:
            taxonomies = {"region": "testapp.Region"}

        class Meta:
            app_label = "testapp"

    class Two(BaseModel):  # noqa: DJ008
        region = models.ManyToManyField(Region, blank=True, related_name="+")

        class Karni:
            taxonomies = {"region": "testapp.Region"}

        class Meta:
            app_label = "testapp"

    class Three(BaseModel):  # noqa: DJ008
        region = models.ManyToManyField(Region, blank=True, related_name="+")

        class Karni:
            taxonomies = {"region": "testapp.Region"}

        class Meta:
            app_label = "testapp"

    project([Region, One, Two, Three])
    assert suggestions.suggest_taxonomies() == []


@isolate_apps("tests.testapp")
def test_a_many_to_many_to_a_plain_model_is_not_a_taxonomy(project: Any) -> None:
    class Tag(BaseModel):  # noqa: DJ008
        class Meta:
            app_label = "testapp"

    class PostOne(BaseModel):  # noqa: DJ008
        tags = models.ManyToManyField(Tag, related_name="+")

        class Meta:
            app_label = "testapp"

    class PostTwo(BaseModel):  # noqa: DJ008
        tags = models.ManyToManyField(Tag, related_name="+")

        class Meta:
            app_label = "testapp"

    class PostThree(BaseModel):  # noqa: DJ008
        tags = models.ManyToManyField(Tag, related_name="+")

        class Meta:
            app_label = "testapp"

    project([Tag, PostOne, PostTwo, PostThree])
    assert suggestions.suggest_taxonomies() == []


# SUG005 a module nothing uses

MANIFEST = """
name = "widgets"
kind = "module"
title = "Widgets"
purpose = "Widgets for the tests."
status = "experimental"
use_when = ["widgets"]
requires = {requires}

[provides]
settings = {{ KARNI_WIDGETS_SIZE = "integer" }}

[wiring]
apps = ["karni_widgets"]
urls = 'path("widgets/", include("karni_widgets.urls"))'
"""


@pytest.fixture
def module_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """A project with the module ``widgets`` added: its app, its URL include, nothing else."""
    monkeypatch.setattr(suggestions, "_root", lambda: tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.py").write_text(
        'INSTALLED_APPS = [\n    # karni:apps\n    "karni_widgets",\n    # /karni:apps\n]\n'
    )
    (tmp_path / "config" / "urls.py").write_text(
        'urlpatterns = [\n    path("widgets/", include("karni_widgets.urls")),\n]\n'
    )
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "views.py").write_text("def index(request): ...\n")

    def install(
        *, requires: str = "[]", other_requires: bool = False, changed: bool = False
    ) -> None:
        manifest = catalog.parse_text(MANIFEST.format(requires=requires), "widgets.toml")
        manifests = [manifest]
        if other_requires:
            manifests.append(
                catalog.parse_text(
                    MANIFEST.replace('"widgets"', '"gadgets"')
                    .replace("karni_widgets", "karni_gadgets")
                    .replace("KARNI_WIDGETS", "KARNI_GADGETS")
                    .format(requires='["widgets"]'),
                    "gadgets.toml",
                )
            )
        monkeypatch.setattr(catalog, "installed", lambda: manifests)
        configs = [SimpleNamespace(name=m.app) for m in manifests]
        monkeypatch.setattr(suggestions.apps, "get_app_configs", lambda: configs)
        value = 5 if changed else 1
        monkeypatch.setattr(
            "karni.facts._modules",
            lambda: [
                {
                    "name": m.name,
                    "settings": {f"KARNI_{m.name.upper()}_SIZE": value},
                    "defaults": {f"KARNI_{m.name.upper()}_SIZE": 1},
                }
                for m in manifests
            ],
        )

    return install


def test_an_added_module_nothing_uses_is_suggested_for_removal(module_project: Any) -> None:
    module_project()
    (found,) = suggestions.suggest_unused_modules()
    assert found.code == "SUG005"
    assert (found.file, found.line) == ("config/settings.py", 3)
    assert found.command == "karni remove widgets"


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("shop/services.py", "from karni_widgets.models import Widget\n"),
        ("shop/templates/index.html", "{% load karni_widgets %}\n"),
        ("config/urls.py", 'path("extra/", include("karni_widgets.other_urls")),\n'),
        ("karni.yaml", "app: shop\nmodules:\n  karni_widgets: {}\n"),
    ],
)
def test_a_module_the_project_uses_is_not_suggested(
    module_project: Any, tmp_path: Path, path: str, text: str
) -> None:
    module_project()
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as handle:
        handle.write(text)
    assert suggestions.suggest_unused_modules() == []


def test_a_module_with_a_changed_setting_or_a_dependent_is_not_suggested(
    module_project: Any,
) -> None:
    module_project(changed=True)
    assert suggestions.suggest_unused_modules() == []
    module_project(other_requires=True)
    assert [item.message.split()[2] for item in suggestions.suggest_unused_modules()] == ["gadgets"]


def test_an_unused_module_suggestion_is_silenced_on_its_settings_line(
    module_project: Any, tmp_path: Path
) -> None:
    module_project()
    settings_file = tmp_path / "config" / "settings.py"
    settings_file.write_text(
        "INSTALLED_APPS = [\n    # karni: allow(suggest-unused-module): used from the admin only\n"
        '    "karni_widgets",\n]\n'
    )
    assert suggestions.suggest_unused_modules() == []
    settings_file.write_text(
        'INSTALLED_APPS = [\n    # karni: allow(suggest-unused-module):\n    "karni_widgets",\n]\n'
    )
    (found,) = suggestions.suggest_unused_modules()
    assert "without a reason" in found.message


# the setting, the command, the exit code


def test_the_setting_turns_every_suggestion_off(monkeypatch: pytest.MonkeyPatch) -> None:
    item = suggestions.Suggestion("SUG001", "a.py", 1, "m", "f")
    assert suggestions.detect([lambda: [item]]) == [item]
    with override_settings(KARNI_SUGGESTIONS=False):
        assert suggestions.detect([lambda: [item]]) == []


def test_a_broken_detector_is_skipped() -> None:
    item = suggestions.Suggestion("SUG002", "a.py", 2, "m", "f")

    def broken() -> list[suggestions.Suggestion]:
        raise RuntimeError("boom")

    assert suggestions.detect([broken, lambda: [item]]) == [item]


def test_the_render_is_compact_and_names_the_rule() -> None:
    item = suggestions.Suggestion(
        "SUG002", "app/models.py", 12, "holds markdown", "use MarkdownField"
    )
    block = suggestions.render([item.as_dict()])
    assert block.splitlines()[0] == "suggestions (1), they never fail the run:"
    assert "[SUG002] app/models.py:12: holds markdown" in block
    assert "fix: use MarkdownField" in block and "karni: allow(<rule>): <reason>" in block
    assert suggestions.render([]) == ""


def test_every_code_has_a_rule_and_a_registry_entry() -> None:
    from karni.errorcodes import get, problems, registry

    for code, rule in suggestions.RULES.items():
        entry = get(code)
        assert entry is not None and entry.kind == "suggestion"
        assert rule.startswith("suggest-") and rule in entry.fix
    assert problems(registry().values()) == []


@pytest.fixture
def one_suggestion(monkeypatch: pytest.MonkeyPatch) -> suggestions.Suggestion:
    item = suggestions.Suggestion("SUG001", "shop/models.py", 7, "a tree by hand", "use TreeModel")
    monkeypatch.setattr(suggestions, "DETECTORS", (lambda: [item],))
    monkeypatch.setattr("karni.management.commands.karni_check.entry_points", lambda **kw: [])
    return item


def test_karni_check_prints_suggestions_last_and_still_passes(
    one_suggestion: suggestions.Suggestion,
) -> None:
    out = StringIO()
    call_command("karni_check", stdout=out, stderr=StringIO())  # no exception: exit code 0
    lines = out.getvalue().splitlines()
    verdict = lines.index("backend checks: ok")
    assert any("[SUG001] shop/models.py:7" in line for line in lines[verdict + 1 :])


def test_karni_check_can_leave_suggestions_out_or_write_them_as_json(
    one_suggestion: suggestions.Suggestion, tmp_path: Path
) -> None:
    out = StringIO()
    call_command("karni_check", "--no-suggestions", stdout=out, stderr=StringIO())
    assert "SUG001" not in out.getvalue()
    target = tmp_path / "out" / "suggestions.json"
    out = StringIO()
    call_command("karni_check", "--suggestions-file", str(target), stdout=out, stderr=StringIO())
    assert "SUG001" not in out.getvalue()
    data = json.loads(target.read_text())
    assert data["version"] == 1 and data["enabled"] is True
    assert data["suggestions"] == [one_suggestion.as_dict()]


def test_karni_check_failures_keep_failing_with_suggestions(
    one_suggestion: suggestions.Suggestion, monkeypatch: pytest.MonkeyPatch
) -> None:
    from karni.exceptions import KarniCommandError

    class Hook:
        name = "broken"

        def load(self) -> Any:
            return lambda: ["something is wrong"]

    monkeypatch.setattr("karni.management.commands.karni_check.entry_points", lambda **kw: [Hook()])
    out, err = StringIO(), StringIO()
    with pytest.raises(KarniCommandError):
        call_command("karni_check", stdout=out, stderr=err)
    assert "something is wrong" in err.getvalue()
    assert "[SUG001]" in out.getvalue()


def test_karni_suggest_prints_json_and_never_fails(one_suggestion: suggestions.Suggestion) -> None:
    out = StringIO()
    call_command("karni_suggest", "--json", stdout=out)
    data = json.loads(out.getvalue())
    assert data == {"version": 1, "enabled": True, "suggestions": [one_suggestion.as_dict()]}
    out = StringIO()
    with override_settings(KARNI_SUGGESTIONS=False):
        call_command("karni_suggest", stdout=out)
    assert "off" in out.getvalue()

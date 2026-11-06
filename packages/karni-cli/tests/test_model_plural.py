"""``karni make model`` and ``karni build`` write ``verbose_name_plural`` when Django's would be wrong.

Django's default plural is the name plus an ``s``: "categorys", "log entrys".
The generators write the right one so the admin, the API and the docs agree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from karni_cli.builder import render
from karni_cli.generators.naming import verbose_plural
from karni_cli.spec.validate import validate_text

from .test_make import ok, project  # noqa: F401 - the project fixture

SPEC = """\
version: 1
app: {name: Catalog}
apps:
  shop:
    entities:
      Category:
        fields: {name: str}
      LogEntry:
        fields: {note: str}
        order: [note]
      Product:
        fields: {name: str}
"""


@pytest.mark.parametrize(
    ("model", "plural"),
    [
        ("Category", "categories"),
        ("LogEntry", "log entries"),
        ("Country", "countries"),
        ("Person", "people"),
        ("Box", "boxes"),
        ("Product", None),
        ("Note", None),
        ("APIKey", None),
    ],
)
def test_the_plural_only_when_djangos_is_wrong(model: str, plural: str | None) -> None:
    assert verbose_plural(model) == plural


def test_make_model_writes_the_plural_with_the_ordering(project: Path) -> None:  # noqa: F811
    ok("make", "app", "shop")
    ok("make", "model", "Category", "name:str:80", "--app", "shop")
    ok("make", "model", "LogEntry", "note:str:80", "--app", "shop", "--order", "-created_at")
    ok("make", "model", "Product", "name:str:80", "--app", "shop")
    source = (project / "shop" / "models.py").read_text()
    assert '    class Meta:\n        verbose_name_plural = "categories"\n' in source
    assert 'ordering = ["-created_at"]\n        verbose_name_plural = "log entries"' in source
    assert source.count("verbose_name_plural") == 2  # Product's own plural is right


def test_build_writes_the_plural_into_the_entity_class() -> None:
    report = validate_text(SPEC)
    assert report.ok and report.spec is not None
    spec = report.spec
    entities = spec.apps["shop"].entities
    texts = {
        name: "\n".join(render._model_class(spec, "shop", name, entities[name], "uuid", 100)[0])
        for name in entities
    }
    assert 'verbose_name_plural = "categories"' in texts["Category"]
    assert 'verbose_name_plural = "log entries"' in texts["LogEntry"]
    assert "verbose_name_plural" not in texts["Product"]


def test_the_cli_and_the_admin_agree_on_every_plural() -> None:
    plurals = pytest.importorskip("karni.admin.plurals")
    for singular in (
        "category", "entry", "country", "log entry", "person", "box", "bus", "status",
        "analysis", "series", "settings", "leaf", "hero", "key", "address", "child",
    ):  # fmt: skip
        name = "".join(part.capitalize() for part in singular.split())
        written = verbose_plural(name)
        assert (written or f"{singular}s") == plurals.plural_of(singular), singular

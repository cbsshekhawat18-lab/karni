"""``manage.py karni_makemigrations`` (experimental): renames first, empty tables need no value."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from karni.management.commands.karni_makemigrations import EmptyTableQuestioner, write_renames
from karni.testing.performance import ScalingCase, _database_marks
from tests.testapp.models import Shelf


@pytest.mark.django_db
def test_a_required_field_on_an_empty_table_needs_no_value() -> None:
    questioner = EmptyTableQuestioner(specified_apps={"testapp"}, log=lambda message: None)
    assert questioner.ask_not_null_addition("floor", "shelf") is None
    Shelf.objects.create(name="Oak")
    with pytest.raises(SystemExit) as stop:  # rows: Django's own answer, as --no-input gives
        questioner.ask_not_null_addition("floor", "shelf")
    assert stop.value.code == 3


def _migrations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *names: str) -> Path:
    package = tmp_path / "renames_migrations"
    package.mkdir()
    (package / "__init__.py").write_text("")
    for name in names:
        (package / f"{name}.py").write_text(
            "from django.db import migrations\n\n\n"
            "class Migration(migrations.Migration):\n    operations = []\n"
        )
    monkeypatch.syspath_prepend(str(tmp_path))
    return package


def test_the_renames_are_written_as_one_migration_after_the_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _migrations(tmp_path, monkeypatch, "0001_initial")
    with override_settings(MIGRATION_MODULES={"testapp": "renames_migrations"}):
        written = write_renames(
            {
                "models": [["testapp", "Rack", "Shelf"]],
                "fields": [["testapp", "Shelf", "title", "name"]],
            }
        )
    assert [Path(path).name for path in written] == ["0002_karni_renames.py"]
    text = (package / "0002_karni_renames.py").read_text()
    assert "('testapp', '0001_initial')" in text
    assert "migrations.RenameModel(" in text and "old_name='Rack'" in text
    assert "migrations.RenameField(" in text and "model_name='shelf'" in text
    sys.modules.pop("renames_migrations", None)


def test_a_generated_column_reading_a_renamed_field_is_dropped_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """karni build's SearchField over search: makemigrations adds it back over the new name."""
    for loaded in [name for name in sys.modules if name.startswith("renames_migrations")]:
        monkeypatch.delitem(sys.modules, loaded)  # an earlier test's migrations, cached
    package = _migrations(tmp_path, monkeypatch)
    (package / "0001_initial.py").write_text(
        "from django.db import migrations, models\n"
        "from karni.fields import SearchField\n\n\n"
        "class Migration(migrations.Migration):\n"
        "    initial = True\n"
        "    operations = [\n"
        "        migrations.CreateModel(\n"
        '            name="Shelf",\n'
        "            fields=[\n"
        '                ("id", models.BigAutoField(primary_key=True)),\n'
        '                ("title", models.CharField(max_length=100)),\n'
        '                ("code", models.CharField(max_length=10)),\n'
        '                ("search", SearchField(sources=["title"])),\n'
        "            ],\n"
        "        ),\n"
        "    ]\n"
    )
    with override_settings(MIGRATION_MODULES={"testapp": "renames_migrations"}):
        write_renames(
            {
                "fields": [
                    ["testapp", "Shelf", "code", "ref"],  # nothing generated reads it
                    ["testapp", "Shelf", "title", "name"],
                ]
            }
        )
    text = (package / "0002_karni_renames.py").read_text()
    assert text.count("migrations.RemoveField(") == 1
    removed = text.index("migrations.RemoveField(")
    assert "name='search'" in text[removed : removed + 120]
    assert removed < text.index("old_name='title'")
    for loaded in [name for name in sys.modules if name.startswith("renames_migrations")]:
        sys.modules.pop(loaded)


def test_two_latest_migrations_have_no_place_for_the_renames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _migrations(tmp_path, monkeypatch, "0001_one", "0001_two")
    with (
        override_settings(MIGRATION_MODULES={"testapp": "renames_migrations"}),
        pytest.raises(CommandError, match="makemigrations --merge"),
    ):
        write_renames({"fields": [["testapp", "Shelf", "title", "name"]]})
    sys.modules.pop("renames_migrations", None)


def test_the_command_refuses_renames_that_are_not_json() -> None:
    with pytest.raises(CommandError, match="--renames is not JSON"):
        call_command("karni_makemigrations", "testapp", "--renames", "{x", "--dry-run")


def test_a_model_on_another_database_is_measured_there() -> None:
    from tests.externalapp.models import ProductMapping, Region

    def case(model: Any) -> ScalingCase:
        return ScalingCase(type("V", (), {"model": model}), "list")

    (mark,) = _database_marks(case(ProductMapping))
    assert mark.name == "django_db" and mark.kwargs == {"databases": ["default", "second"]}
    assert _database_marks(case(Region)) == []

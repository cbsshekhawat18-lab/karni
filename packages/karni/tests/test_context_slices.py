"""Context slices (experimental): ``manage.py karni_context --summary / --app / --model``."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from karni.introspect import (
    ContextSliceError,
    app_context,
    build_context,
    field_text,
    key_type,
    model_context,
    resolve_models,
    summary_context,
)
from tests.testapp.models import Event


def _keys(text: str) -> list[str]:
    return [line.split(":", 1)[0] for line in text.split("\n")]


def test_summary_has_one_line_per_app_with_counts() -> None:
    lines = summary_context().split("\n")
    assert lines[0].startswith("SUMMARY: ") and "karni context --app <label>" in lines[0]
    testapp = next(line for line in lines if line.startswith("APP testapp: "))
    assert "Event" in testapp and "Venue" in testapp
    assert ", 4 viewsets, 0 pages" in testapp
    assert all(line.startswith("APP ") for line in lines[1:])


def test_pages_named_after_a_model_count_for_its_app(settings, tmp_path: Path) -> None:
    pages = tmp_path / "frontend" / "src" / "pages"
    (pages / "karni").mkdir(parents=True)
    for name in ("events.tsx", "karni/event-detail.tsx", "karni/event-form.tsx", "home.tsx"):
        (pages / name).write_text("")
    (pages / "events.test.tsx").write_text("")
    settings.BASE_DIR = tmp_path
    testapp = next(line for line in summary_context().split("\n") if "APP testapp" in line)
    assert testapp.endswith(", 3 pages")
    assert "PAGES: events karni/event-detail karni/event-form" in app_context(["testapp"])
    assert "PAGES: events karni/event-detail karni/event-form" in model_context(["Event"])


def test_app_slice_has_every_model_and_only_that_app() -> None:
    text = app_context(["testapp"])
    assert _keys(text)[0] == "MODELS" and _keys(text)[-1] == "BASES"
    models_line = text.split("\n")[0]
    assert "Event(title,description,starts_at,capacity,status," in models_line
    assert "Novel(" not in models_line  # perfapp is another area
    relations = next(line for line in text.split("\n") if line.startswith("RELATIONS: "))
    assert "Event.venue->Venue" in relations and "Event.organizer->karni_accounts.User" in relations
    viewsets = next(line for line in text.split("\n") if line.startswith("VIEWSETS: "))
    assert "EventViewSet(events read=Public() write=Authenticated())" in viewsets
    assert "MODULES:" not in text and "FEATURES:" not in text


def test_app_slice_names_relations_from_other_apps() -> None:
    text = app_context(["perfapp"])
    assert "RELATIONS: " in text
    assert any(line.startswith("KEYS: ") for line in text.split("\n"))


def test_model_slice_lists_every_field_and_its_viewsets() -> None:
    text = model_context(["testapp.Event"])
    lines = text.split("\n")
    assert lines[0].startswith("MODEL: testapp.Event (tests/testapp/models.py:")
    assert lines[0].endswith(f"key {key_type(Event)}, table testapp_event")
    assert lines[1].startswith("FIELDS: title str:200, description text?")
    assert "status str:20 choices(draft,published)" in lines[1]
    assert "venue fk:Venue?" in lines[1] and "tags m2m:Tag?" in lines[1]
    assert any("search=title" in line for line in lines)


def test_field_text_speaks_the_spec() -> None:
    assert field_text(Event._meta.get_field("title")) == "title str:200"
    assert field_text(Event._meta.get_field("capacity")) == "capacity int?"


def test_unknown_and_ambiguous_names_say_what_exists() -> None:
    with pytest.raises(ContextSliceError) as unknown:
        model_context(["Evnt"])
    assert unknown.value.code == "E470" and "Did you mean Event" in unknown.value.message
    with pytest.raises(ContextSliceError) as ambiguous:
        resolve_models(["Customer"])
    assert ambiguous.value.code == "E471"
    assert "fieldsapp.Customer, testapp.Customer" in ambiguous.value.message
    with pytest.raises(ContextSliceError) as app:
        app_context(["tesapp"])
    assert app.value.code == "E470" and "testapp" in app.value.message


def test_the_command_takes_the_slices_and_keeps_its_default() -> None:
    out = StringIO()
    call_command("karni_context", stdout=out)
    assert out.getvalue().strip() == build_context().strip()
    out = StringIO()
    call_command("karni_context", app=["testapp"], model=["Event"], stdout=out)
    keys = _keys(out.getvalue().strip())
    assert keys[0] == "MODELS" and "MODEL" in keys and keys.index("BASES") < keys.index("MODEL")
    with pytest.raises(CommandError, match="E470"):
        call_command("karni_context", model=["Nope"], stdout=StringIO())

"""Tests for the karni_context / karni_check management commands.

These run against the shared tests/settings.py (testapp + adminapp installed),
so they assert per-app subsets rather than a cross-builder golden string.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

import karni
from karni.introspect import BASES, build_context


def _sections(output: str) -> dict[str, str]:
    return {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in output.strip().split("\n")
        if ":" in line
    }


@pytest.mark.django_db
def test_context_command_shape() -> None:
    out = StringIO()
    call_command("karni_context", stdout=out)
    sections = _sections(out.getvalue())
    assert "MODELS" in sections and "BASES" in sections
    # section order is fixed
    keys = [line.split(":", 1)[0] for line in out.getvalue().strip().split("\n")]
    assert keys == [k for k in ("MODELS", "VIEWSETS", "MODULES", "BASES") if k in keys]


def test_bases_line_matches_real_exports() -> None:
    """BASES is a versioned constant — every name must import from karni."""
    from karni.accounts.models import AbstractKarniUser  # noqa: F401
    from karni.admin import KarniModelAdmin  # noqa: F401
    from karni.api import BaseViewSet  # noqa: F401
    from karni.models import (  # noqa: F401
        AuditedModel,
        BaseModel,
        SoftDeleteModel,
        TimestampedModel,
        UUIDModel,
    )

    resolved = {
        "BaseModel",
        "UUIDModel",
        "TimestampedModel",
        "SoftDeleteModel",
        "AuditedModel",
        "BaseViewSet",
        "KarniModelAdmin",
        "AbstractKarniUser",
    }
    assert set(BASES) == resolved
    assert karni.__version__


@pytest.mark.django_db
def test_models_section_covers_testapp_and_skips_framework() -> None:
    output = build_context()
    models_line = _sections(output)["MODELS"]
    assert "Event(" in models_line
    assert "Venue(" in models_line
    # framework noise excluded
    for absent in ("User(", "OneTimeToken(", "Session(", "Permission(", "PeriodicTask("):
        assert absent not in models_line, absent
    # audit fields never listed
    assert "created_at" not in models_line


@pytest.mark.django_db
def test_field_cap_and_declaration_order() -> None:
    models_line = _sections(build_context())["MODELS"]
    event_fields = models_line.split("Event(")[1].split(")")[0].split(",")
    assert 0 < len(event_fields) <= 4
    assert event_fields[0] == "title"


@pytest.mark.django_db
def test_viewsets_section_lists_registered() -> None:
    sections = _sections(build_context())
    assert "EventViewSet" in sections.get("VIEWSETS", "")


@pytest.mark.django_db
def test_skip_apps_setting_override(settings) -> None:
    settings.KARNI_CONTEXT_SKIP_APPS = ["testapp", "adminapp"] + list(
        __import__("karni.introspect", fromlist=["CONTEXT_SKIP_APPS"]).CONTEXT_SKIP_APPS
    )
    output = build_context()
    assert "Event(" not in output


@pytest.mark.django_db
def test_karni_check_ok() -> None:
    out = StringIO()
    call_command("karni_check", stdout=out)
    assert "karni check: ok" in out.getvalue()


def test_karni_check_hook_failures(monkeypatch) -> None:
    """Entry-point hooks: failures collected, exceptions recorded, exit nonzero."""
    import karni.management.commands.karni_check as cmd_mod

    class FakeEP:
        def __init__(self, name, fn):
            self.name = name
            self._fn = fn

        def load(self):
            return self._fn

    eps = [
        FakeEP("boom", lambda: (_ for _ in ()).throw(RuntimeError("exploded"))),
        FakeEP("layers", lambda: ["fat model detected"]),
        FakeEP("clean", lambda: []),
    ]
    monkeypatch.setattr(cmd_mod, "entry_points", lambda group: eps)

    from django.core.management.base import CommandError

    err = StringIO()
    with pytest.raises(CommandError, match="2 failure"):
        call_command("karni_check", stderr=err)
    text = err.getvalue()
    assert "boom: exploded" in text and "layers: fat model detected" in text

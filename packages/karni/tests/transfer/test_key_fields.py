"""``Karni.natural_key`` and ``import_key`` name one field, as a string (``karni.E291``).

A list (``natural_key = ["name"]``) passed ``karni check`` and then every
request that read the model answered 500 with "natural_key names
\"['name']\"". ``karni check`` now refuses it and names the fix, and the
readers raise the same code and message.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.apps import apps

from karni.checks import check_key_fields
from karni.exceptions import KarniImproperlyConfigured
from karni.meta import import_options, natural_key
from tests.testapp.models import Event, Venue

pytestmark = pytest.mark.django_db  # the package's conftest opens the database


def _messages() -> list[Any]:
    return check_key_fields([apps.get_app_config("testapp")])


def test_the_declared_string_passes() -> None:
    assert natural_key(Venue) == "name"
    assert _messages() == []


@pytest.mark.parametrize("declared", [["name"], ("name",)])
def test_a_one_field_list_is_refused_with_the_string_form(
    monkeypatch: pytest.MonkeyPatch, declared: Any
) -> None:
    monkeypatch.setattr(Venue.Karni, "natural_key", declared)
    found = _messages()
    assert [message.id for message in found] == ["karni.E291"]
    assert "natural_key = 'name'" in found[0].msg and "Venue.Karni.natural_key" in found[0].msg
    with pytest.raises(KarniImproperlyConfigured, match="natural_key = 'name'") as caught:
        natural_key(Venue)
    assert caught.value.code == "E291"


def test_a_key_of_several_fields_says_it_is_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Venue.Karni, "natural_key", ["name", "city"])
    (message,) = _messages()
    assert message.id == "karni.E291"
    assert "several fields is not supported" in message.msg and "SlugField" in message.msg


def test_a_missing_field_is_reported_at_check_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Venue.Karni, "natural_key", "title")
    (message,) = _messages()
    assert message.id == "karni.E291" and "'title'" in message.msg


def test_import_key_follows_the_same_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Event.Karni, "import_key", ["title"], raising=False)
    (message,) = _messages()
    assert message.id == "karni.E291" and "Event.Karni.import_key" in message.msg
    with pytest.raises(KarniImproperlyConfigured, match="import_key = 'title'"):
        import_options(Event)


def test_the_system_check_reports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """What ``karni check`` runs: the models checks report the list form."""
    from django.core import checks

    monkeypatch.setattr(Venue.Karni, "natural_key", ["name"])
    found = checks.run_checks(app_configs=[apps.get_app_config("testapp")], tags=["models"])
    assert "karni.E291" in [message.id for message in found]

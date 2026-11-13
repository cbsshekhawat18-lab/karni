"""The contracts the visits part requires are installed, and its event is declared."""

from django.conf import settings

from karni.outbox.bus import registry


def test_the_contracts_it_requires_are_installed() -> None:
    assert "karni.people" in settings.INSTALLED_APPS
    assert "karni.outbox" in settings.INSTALLED_APPS


def test_its_event_is_declared() -> None:
    assert registry.declaration("visits.visit.logged", 1) is not None

"""``karni.imports.import_setting``: a KARNI_* dotted path that cannot be imported is E506."""

from __future__ import annotations

import pytest
from django.test import override_settings

from karni.exceptions import KarniImproperlyConfigured
from karni.imports import import_setting


def test_returns_the_object_and_passes_objects_through() -> None:
    from karni.api.search.simple import SimpleSearchProvider

    assert import_setting("X", "karni.api.search.simple.SimpleSearchProvider") is (
        SimpleSearchProvider
    )
    assert import_setting("X", SimpleSearchProvider) is SimpleSearchProvider


def test_a_missing_module_is_a_configuration_error_naming_the_setting() -> None:
    with pytest.raises(KarniImproperlyConfigured) as caught:
        import_setting("KARNI_SEARCH_PROVIDER", "nowhere.Provider")
    assert caught.value.code == "E506"
    assert "KARNI_SEARCH_PROVIDER" in str(caught.value) and "nowhere" in str(caught.value)
    with pytest.raises(KarniImproperlyConfigured) as kept:
        import_setting("KARNI_ACCOUNTS_EMAIL_BACKEND", "myproject.mail.Backend", code="E201")
    assert kept.value.code == "E201"


def test_the_search_provider_and_the_email_backend_report_their_setting() -> None:
    from karni.accounts.emails import get_email_backend
    from karni.api.search import get_search_provider

    with override_settings(KARNI_SEARCH_PROVIDER="nowhere.Provider"):
        with pytest.raises(KarniImproperlyConfigured, match="E506: KARNI_SEARCH_PROVIDER"):
            get_search_provider()
    with override_settings(KARNI_ACCOUNTS_EMAIL_BACKEND="myproject.mail.Backend"):
        with pytest.raises(KarniImproperlyConfigured, match="E201: KARNI_ACCOUNTS_EMAIL_BACKEND"):
            get_email_backend()

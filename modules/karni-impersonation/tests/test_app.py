"""The module contract: app, fragment, error codes, checks."""

from __future__ import annotations

from typing import Any

import pytest
from django.apps import apps
from karni.errorcodes import registry

from karni_impersonation import checks, conf


def test_app_is_installed() -> None:
    assert apps.get_app_config("karni_impersonation").name == "karni_impersonation"


def test_settings_fragment_is_a_dict() -> None:
    assert isinstance(conf.DEFAULTS, dict) and conf.get("KARNI_IMPERSONATION_MAX_MINUTES") == 60
    assert "*:delete" in conf.get("KARNI_IMPERSONATION_BLOCKED")


def test_error_codes_are_registered() -> None:
    codes = registry()
    assert "IMP001" in codes and "IMP008" in codes


@pytest.mark.django_db
def test_checks_require_the_wiring(settings: Any) -> None:
    assert checks.run_checks() == []
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "karni_impersonation" not in m]
    failures = checks.run_checks()
    assert failures and "IMP007" in failures[0] and "MIDDLEWARE" in failures[0]
    settings.KARNI_IMPERSONATION_BLOCKED = ["ok", 5]
    assert any("IMP008" in failure for failure in checks.run_checks())

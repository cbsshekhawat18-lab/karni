"""The module contract: app, fragment, error codes, checks and the policy reader."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.apps import apps
from karni.errorcodes import registry
from karni.exceptions import KarniImproperlyConfigured

from karni_approvals import checks, conf
from karni_approvals.meta import approval_policy, clear_caches
from tests.testapp.models import Contract, Invoice, Memo


def test_app_is_installed() -> None:
    assert apps.get_app_config("karni_approvals").name == "karni_approvals"


def test_settings_fragment_is_a_dict() -> None:
    assert isinstance(conf.DEFAULTS, dict) and conf.get("KARNI_APPROVALS_REQUIRED") == 1


def test_error_codes_are_registered() -> None:
    codes = registry()
    assert (
        "APR001" in codes
        and "APR007" in codes
        and codes["APR002"].source.startswith("karni_approvals")
    )


def test_policies_are_read_from_class_karni() -> None:
    invoice = approval_policy(Invoice)
    assert invoice is not None and invoice.fields == ("amount", "status") and invoice.approvals == 1
    assert invoice.roles == () and invoice.timeout is None and invoice.on_timeout == "expire"
    contract = approval_policy(Contract)
    assert contract is not None and contract.any_change and contract.approvals == 2
    assert contract.roles == ("finance",) and contract.timeout == timedelta(hours=1)
    assert contract.on_timeout == "escalate" and contract.escalation_roles == ("staff",)
    assert approval_policy(Memo) is None


@pytest.mark.django_db
def test_checks_pass_for_the_test_project_and_catch_a_bad_policy(monkeypatch: Any) -> None:
    assert checks.run_checks() == []
    monkeypatch.setattr(Invoice.Karni, "approver_roles", ["nobody"], raising=False)
    clear_caches()
    try:
        failures = checks.run_checks()
        assert failures and "nobody" in failures[0]
        monkeypatch.setattr(Invoice.Karni, "requires_approval", ["amount", "nope"])
        clear_caches()
        with pytest.raises(KarniImproperlyConfigured, match="APR007"):
            approval_policy(Invoice)
    finally:
        clear_caches()

"""Each endpoint is limited per caller under its own scope, and answers 429 past the limit."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from karni_storage.checks import run_checks
from karni_storage.throttling import DEFAULT_RATES, storage_rate

pytestmark = pytest.mark.django_db

PDF = {"name": "guide.pdf", "content_type": "application/pdf", "size": 2048}


def _limit(settings: Any, **rates: str | None) -> None:
    settings.KARNI_STORAGE_THROTTLE_RATES = {**DEFAULT_RATES, **rates}


def test_the_download_answers_429_past_its_limit(
    owner_api: APIClient, other_api: APIClient, make_product: Any, settings: Any
) -> None:
    _limit(settings, download="2/min")
    product = make_product()
    product.manual.save("guide.txt", ContentFile(b"hello"), save=True)
    path = f"/api/products/{product.pk}/files/manual/"
    assert [owner_api.get(path).status_code for _ in range(2)] == [200, 200]
    limited = owner_api.get(path)
    assert limited.status_code == 429 and "Retry-After" in limited
    # Per caller: another user still gets through (to the viewset's 404 for their row).
    assert other_api.get(path).status_code == 404


def test_the_upload_step_answers_429_past_its_limit(owner_api: APIClient, settings: Any) -> None:
    _limit(settings, upload="1/min")
    path = "/api/products/files/manual/upload/"
    assert owner_api.post(path, PDF, format="json").status_code == 200
    assert owner_api.post(path, PDF, format="json").status_code == 429


def test_confirm_answers_429_past_its_limit(owner_api: APIClient, settings: Any) -> None:
    _limit(settings, confirm="1/min")
    path = "/api/products/files/manual/confirm/"
    # On local storage confirm refuses (STORE015), but the limit is checked first.
    assert owner_api.post(path, {"token": "x"}, format="json").status_code == 400
    assert owner_api.post(path, {"token": "x"}, format="json").status_code == 429


def test_the_scopes_are_separate(owner_api: APIClient, settings: Any) -> None:
    _limit(settings, upload="1/min", confirm="1/min")
    upload = owner_api.post("/api/products/files/manual/upload/", PDF, format="json")
    assert upload.status_code == 200
    confirm = owner_api.post("/api/products/files/manual/confirm/", {"token": "x"}, format="json")
    assert confirm.status_code == 400


def test_the_drf_setting_of_a_scope_wins_and_none_turns_a_limit_off(settings: Any) -> None:
    assert storage_rate("download") == "1000/hour"
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {}),
            "storage.download": "5/min",
            "storage.upload": None,
        },
    }
    assert storage_rate("download") == "5/min"
    assert storage_rate("upload") is None
    settings.KARNI_STORAGE_THROTTLE_RATES = {"confirm": None}
    assert storage_rate("confirm") is None


def test_a_rate_the_setting_does_not_take_fails_karni_check(settings: Any) -> None:
    settings.KARNI_STORAGE_THROTTLE_RATES = {"download": "lots", "delete": "1/min"}
    found = [problem for problem in run_checks() if problem.startswith("STORE005")]
    assert len(found) == 2
    assert "'lots'" in found[0] and "'delete'" in found[1]

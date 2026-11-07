"""karni check: the preset, its credentials, the URL include and the viewsets."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings

from karni_storage.checks import run_checks

pytestmark = pytest.mark.django_db

BROCHURE = "STORE006: testapp.Brochure.scan is protected, but no viewset serves Brochure on the API"


def test_a_working_project_has_one_problem_the_test_app_planted() -> None:
    found = run_checks()
    assert len(found) == 1 and found[0].startswith(BROCHURE)


def test_the_url_include_is_checked() -> None:
    with override_settings(ROOT_URLCONF="tests.urls_without_storage"):
        found = run_checks()
    assert any(problem.startswith("STORE004") for problem in found)
    assert 'path("api/", include("karni_storage.urls"))' in " ".join(found)


def test_preset_problems_reach_karni_check() -> None:
    with override_settings(KARNI_STORAGE="s3", KARNI_STORAGE_PROVIDER="r2", R2_ACCOUNT_ID=""):
        codes = [problem.split(":")[0] for problem in run_checks()]
    assert codes == ["STORE003", "STORE006"]
    with override_settings(KARNI_STORAGE_PROVIDER="dropbox"):
        assert run_checks()[0].startswith("STORE001")


def test_thumbnail_sizes_are_checked(settings: Any) -> None:
    settings.KARNI_STORAGE_THUMBNAIL_SIZES = {"small": [160]}
    found = run_checks()
    assert found[0].startswith("STORE005") and "[width, height]" in found[0]


def test_the_check_runs_through_karni_check(capsys: Any) -> None:
    from django.core.management import call_command
    from karni.exceptions import KarniCommandError

    with pytest.raises(KarniCommandError):
        call_command("karni_check")
    assert BROCHURE in capsys.readouterr().err


def test_the_modules_codes_are_registered() -> None:
    from karni.errorcodes import get

    for code in ("STORE001", "STORE004", "STORE011", "STORE013", "STORE020"):
        found = get(code)
        assert found is not None and found.code == code

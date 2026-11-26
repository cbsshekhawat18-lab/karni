"""KARNI_SITE_EDITOR_GRANTS: grants merged over the editor role's own, set in settings.py as
plain data, checked by karni check (SITE026). A role in KARNI_ROLES still replaces it all."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from karni.accounts.roles import declared_roles, sync_roles
from pytest_django import Settings

from karni_site import checks
from karni_site.roles import editor_grants
from tests.conftest import make_user

pytestmark = pytest.mark.django_db

MODULE = Path(__file__).resolve().parents[1]


def editor_spec() -> Any:
    return next(spec for spec in declared_roles() if spec.slug == "editor")


def opens(user: Any, url_name: str) -> int:
    client = Client()
    client.force_login(user)
    return client.get(reverse(url_name)).status_code


def test_the_grants_join_the_role_and_open_the_admin_page(settings: Settings) -> None:
    settings.KARNI_SITE_EDITOR_GRANTS = {
        "testapp.service:*": "all",
        "karni_site.block:view": "all",  # the module's own grant, given again
    }
    spec = editor_spec()
    assert spec.grants == {**editor_grants(), "testapp.service:*": "all"}
    sync_roles()
    editor = make_user("editor@example.com", "editor", staff=True)
    assert opens(editor, "admin:testapp_service_changelist") == 200
    assert opens(editor, "admin:karni_site_block_changelist") == 200
    assert opens(editor, "admin:testapp_enquiry_changelist") == 403
    assert checks.run_checks() == []


def test_without_the_setting_the_role_is_as_before(roles: None) -> None:
    assert editor_spec().grants == editor_grants()
    editor = make_user("editor@example.com", "editor", staff=True)
    assert opens(editor, "admin:testapp_service_changelist") == 403


def test_settings_set_it_while_they_load(tmp_path: Path) -> None:
    # What the reporter could not do with editor_grants(): nothing is imported, and the
    # role is built from it once the apps are ready.
    (tmp_path / "grants_settings.py").write_text(
        "from tests.settings import *  # noqa: F403\n"
        'KARNI_SITE_EDITOR_GRANTS = {"testapp.service:change": "all"}\n',
        encoding="utf-8",
    )
    script = (
        "import django; django.setup()\n"
        "from karni.accounts.roles import declared_roles\n"
        "spec = next(s for s in declared_roles() if s.slug == 'editor')\n"
        "print(spec.grants['testapp.service:change'], spec.grants['karni_site.block:change'])\n"
    )
    environment = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "grants_settings",
        "PYTHONPATH": os.pathsep.join([str(MODULE), str(tmp_path)]),
    }
    environment.pop("VIRTUAL_ENV", None)
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=MODULE,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "all all"


def test_a_grant_the_role_cannot_give_is_left_out_and_named(settings: Settings) -> None:
    settings.KARNI_SITE_EDITOR_GRANTS = {
        "testapp.servise:*": "all",  # a typo
        "testapp.service:publish": "all",  # an action the model does not have
        "testapp.service:view": "related:branch",  # Service has no such scope path
        "testapp.service:change": "all",
    }
    spec = editor_spec()
    assert spec.grants == {**editor_grants(), "testapp.service:change": "all"}
    sync_roles()  # the sync after migrate does not fail on them
    failures = checks.run_checks()
    assert [failure.split(" is not granted")[0] for failure in failures] == [
        "SITE026: KARNI_SITE_EDITOR_GRANTS['testapp.servise:*']",
        "SITE026: KARNI_SITE_EDITOR_GRANTS['testapp.service:publish']",
        "SITE026: KARNI_SITE_EDITOR_GRANTS['testapp.service:view']",
    ]
    assert "no installed model is 'testapp.servise'" in failures[0]
    assert "Did you mean 'testapp.service'" in failures[0]
    assert "testapp.service has no action 'publish'. Its actions: add, change" in failures[1]
    assert "scope 'related:branch', but Service declares no scope path" in failures[2]
    assert "KARNI_ROLES" not in failures[2]


def test_a_role_in_karni_roles_still_replaces_the_whole_role(settings: Settings) -> None:
    settings.KARNI_SITE_EDITOR_GRANTS = {"testapp.service:*": "all"}
    settings.KARNI_ROLES = {
        "editor": {"name": "Copy editor", "grants": {"karni_site.block:view": "all"}}
    }
    spec = editor_spec()
    assert (spec.name, spec.grants) == ("Copy editor", {"karni_site.block:view": "all"})
    (failure,) = checks.run_checks()
    assert failure.startswith("SITE026: KARNI_SITE_EDITOR_GRANTS is set, but KARNI_ROLES names")
    assert "Put the grants in KARNI_ROLES['editor']" in failure


def test_the_setting_without_a_role_or_as_a_list_is_reported(settings: Settings) -> None:
    settings.KARNI_SITE_EDITOR_GRANTS = {"testapp.service:*": "all"}
    settings.KARNI_SITE_EDITOR_ROLE = None
    (failure,) = checks.run_checks()
    assert "KARNI_SITE_EDITOR_ROLE is None" in failure
    settings.KARNI_SITE_EDITOR_ROLE = "editor"
    settings.KARNI_SITE_EDITOR_GRANTS = ["testapp.service:*"]
    (failure,) = checks.run_checks()
    assert failure.startswith("SITE026: KARNI_SITE_EDITOR_GRANTS is a list. It is a dict of")
    assert editor_spec().grants == editor_grants()

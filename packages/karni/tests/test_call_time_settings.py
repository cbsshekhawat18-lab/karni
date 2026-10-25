"""The settings contract: what ``karni_settings()`` reads during the call.

A setting assigned after the call normally wins. The few that the call reads
to compute other settings (``karni.conf.CALL_TIME_SETTINGS``) cannot win that
way, so ``karni.E508`` fails startup and names each one reassigned after the
call. ``KARNI_ADMIN_LOGO`` is resolved per request instead (test_admin_logo).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.test import override_settings

from karni.checks import check_call_time_settings
from karni.conf import CALL_TIME_SETTINGS, karni_settings, settings_changed_after_call
from karni.errorcodes import docs_url

MODULE = "tests.fake_project_settings"

#: A value differing from the dev default, per call-time setting.
CHANGED: dict[str, Any] = {
    "KARNI_AUTH_MODE": "session",
    "KARNI_2FA": True,
    "KARNI_SOCIAL_AUTH": True,
    "KARNI_SOCIAL_PROVIDERS": ["github"],
    "KARNI_FRONTEND_URL": "https://app.example.com",
    "KARNI_AUTH_THROTTLE_RATES": {"auth.login": "1/min"},
    "KARNI_JSON_LOGS": True,
    "KARNI_CACHE": "locmem",
    "KARNI_STORAGE": "s3",
}
#: What the call must have used for the setting to feed anything.
NEEDS: dict[str, dict[str, Any]] = {
    "KARNI_SOCIAL_PROVIDERS": {"KARNI_SOCIAL_AUTH": True, "KARNI_AUTH_MODE": "session"},
    "KARNI_FRONTEND_URL": {"KARNI_AUTH_MODE": "session"},
}


def _namespace(**before: Any) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__name__": MODULE, "SECRET_KEY": "x" * 50, **before}
    karni_settings(namespace, env_name="dev")
    return namespace


@pytest.fixture(autouse=True)
def _forget() -> Iterator[None]:
    from karni import conf

    yield
    conf._consumed.pop(MODULE, None)


def _e508() -> list[Any]:
    with override_settings(SETTINGS_MODULE=MODULE):
        return [m for m in check_call_time_settings() if m.id == "karni.E508"]


def test_every_call_time_setting_is_covered() -> None:
    assert set(CHANGED) == set(CALL_TIME_SETTINGS)


@pytest.mark.parametrize("name", sorted(CALL_TIME_SETTINGS))
def test_a_setting_assigned_after_the_call_fails_startup(name: str) -> None:
    namespace = _namespace(**NEEDS.get(name, {}))
    namespace[name] = CHANGED[name]
    assert set(settings_changed_after_call(MODULE)) == {name}
    (message,) = _e508()
    assert message.obj == name
    assert f"{name} is assigned after karni_settings() in {MODULE}" in message.msg
    assert CALL_TIME_SETTINGS[name] in message.msg
    assert "above the karni_settings(globals()) line" in message.hint
    assert docs_url("E508") in message.hint


@pytest.mark.parametrize("name", sorted(CALL_TIME_SETTINGS))
def test_the_same_value_assigned_before_the_call_is_fine(name: str) -> None:
    _namespace(**{**NEEDS.get(name, {}), name: CHANGED[name]})
    assert settings_changed_after_call(MODULE) == {}
    assert _e508() == []


def test_a_list_or_dict_changed_in_place_counts() -> None:
    namespace = _namespace(KARNI_AUTH_MODE="session", KARNI_SOCIAL_AUTH=True)
    namespace["KARNI_SOCIAL_PROVIDERS"] += ["github"]
    namespace["KARNI_AUTH_THROTTLE_RATES"]["auth.login"] = "1/min"
    assert set(settings_changed_after_call(MODULE)) == {
        "KARNI_SOCIAL_PROVIDERS",
        "KARNI_AUTH_THROTTLE_RATES",
    }


def test_inputs_the_call_did_not_use_are_not_reported() -> None:
    namespace = _namespace(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        LOGGING={"version": 1},
    )
    namespace["KARNI_CACHE"] = "locmem"  # the project's own CACHES: nothing derived
    namespace["KARNI_JSON_LOGS"] = True  # the project's own LOGGING: nothing derived
    namespace["KARNI_FRONTEND_URL"] = "https://app.example.com"  # jwt mode: nothing derived
    namespace["KARNI_SOCIAL_PROVIDERS"] = ["github"]  # social auth off: nothing derived
    assert settings_changed_after_call(MODULE) == {}


def test_a_namespace_without_a_module_name_and_override_settings_are_ignored() -> None:
    karni_settings({"SECRET_KEY": "x" * 50}, env_name="dev")
    assert settings_changed_after_call(None) == {}
    _namespace()
    with override_settings(KARNI_AUTH_MODE="session"):  # tests change settings, not the module
        assert _e508() == []


def test_karni_cache_and_storage_defined_before_the_call_build_caches_and_storages() -> None:
    namespace = _namespace(KARNI_CACHE="locmem", KARNI_STORAGE="s3")
    assert namespace["CACHES"]["default"]["BACKEND"].endswith("LocMemCache")
    assert namespace["STORAGES"]["default"]["BACKEND"] == "karni.storage.S3Storage"
    passed: dict[str, Any] = {"__name__": MODULE, "SECRET_KEY": "x" * 50}
    karni_settings(passed, env_name="dev", KARNI_CACHE="locmem")
    assert passed["CACHES"]["default"]["BACKEND"].endswith("LocMemCache")


def test_an_unfold_replaced_after_the_call_drops_the_logo() -> None:
    with override_settings(KARNI_ADMIN_LOGO="karni", UNFOLD={"SITE_TITLE": "Ops"}):
        (message,) = check_call_time_settings()
    assert message.id == "karni.E508" and message.obj == "KARNI_ADMIN_LOGO"
    assert "UNFOLD has no 'SITE_LOGO' entry" in message.msg
    with override_settings(UNFOLD={"SITE_TITLE": "Ops"}):  # no logo asked for: fine
        assert check_call_time_settings() == []


def test_the_real_settings_module_passes() -> None:
    assert check_call_time_settings() == []

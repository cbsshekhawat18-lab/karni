"""The pytest plugin gives every test an empty local-memory cache (karni_test_cache).

Each case runs pytest in a subprocess on a tiny project whose ``CACHES`` point
at a Redis that does not exist: a test that wrote to the project's own cache
would fail to connect, so a passing run proves the tests never touched it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

SETTINGS = """
SECRET_KEY = "plugin-cache-test"
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
# Port 9 (discard): nothing answers, so any use of these caches fails.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://127.0.0.1:9/0",
        "KEY_PREFIX": "shop",
        "TIMEOUT": 60,
    },
    "pages": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://127.0.0.1:9/1",
    },
    "off": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
}
"""

TESTS = """
import pytest
from django.conf import settings
from django.core.cache import cache, caches


def test_one_writes_to_every_alias():
    cache.set("queued", 1)
    caches["pages"].set("queued", 1)
    assert cache.get("queued") == 1 and caches["pages"].get("queued") == 1


def test_the_next_starts_empty():
    assert cache.get("queued") is None and caches["pages"].get("queued") is None
    default = settings.CACHES["default"]
    assert default["BACKEND"].endswith("LocMemCache")
    assert default["KEY_PREFIX"] == "shop" and default["TIMEOUT"] == 60
    assert settings.CACHES["off"]["BACKEND"].endswith("DummyCache")


@pytest.mark.karni_project_cache
def test_a_marked_test_keeps_the_project_cache():
    assert settings.CACHES["default"]["BACKEND"].endswith("RedisCache")
"""

PROJECT_ONLY = """
from django.conf import settings


def test_the_ini_keeps_the_project_cache():
    assert settings.CACHES["default"]["BACKEND"].endswith("RedisCache")
"""


#: A session fixture first set up during a test, as pytest-django's database setup is.
SESSION_CONFTEST = """
import pytest
from django.conf import settings


@pytest.fixture(scope="session")
def _session_setting():
    settings.MIGRATION_MODULES = {"auth": None}


@pytest.fixture(autouse=True)
def _lazy(request):
    request.getfixturevalue("_session_setting")
"""

SESSION_TESTS = """
from django.conf import settings


def test_first_sets_it_up():
    assert settings.MIGRATION_MODULES == {"auth": None}


def test_a_later_test_still_sees_it():
    assert settings.MIGRATION_MODULES == {"auth": None}
"""


def _run(
    tmp_path: Path, tests: str, *args: str, conftest: str = ""
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "cache_settings.py").write_text(textwrap.dedent(SETTINGS))
    (tmp_path / "test_inner.py").write_text(textwrap.dedent(tests))
    (tmp_path / "conftest.py").write_text(textwrap.dedent(conftest))
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "PYTEST_", "KARNI_"))
    }
    env.update(DJANGO_SETTINGS_MODULE="cache_settings", PYTHONPATH=str(tmp_path))
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, "test_inner.py"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_each_test_gets_an_empty_local_memory_cache(tmp_path: Path) -> None:
    result = _run(tmp_path, TESTS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout


def test_the_ini_option_keeps_the_project_cache(tmp_path: Path) -> None:
    result = _run(tmp_path, PROJECT_ONLY, "-o", "karni_test_cache=project")
    assert result.returncode == 0, result.stdout + result.stderr
    refused = _run(tmp_path, PROJECT_ONLY, "-o", "karni_test_cache=redis")
    assert refused.returncode != 0
    assert "karni_test_cache = 'redis' is not valid" in refused.stdout + refused.stderr


def test_settings_a_session_fixture_sets_during_a_test_are_kept(tmp_path: Path) -> None:
    """Only CACHES is put back after a test (pytest-django --no-migrations relies on it)."""
    result = _run(tmp_path, SESSION_TESTS, conftest=SESSION_CONFTEST)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout

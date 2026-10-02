"""Tests for the :func:`karni.celery.create_celery_app` factory.

Django settings come from ``tests/settings.py`` via the
``DJANGO_SETTINGS_MODULE`` pytest configuration; nothing here configures
Django itself.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest
from celery import Celery
from django.conf import settings

from karni.celery import create_celery_app


class TestAppName:
    """The factory names the app from its argument, then PROJECT_NAME env."""

    def test_default_name_is_karni(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PROJECT_NAME", raising=False)
        app = create_celery_app()
        assert isinstance(app, Celery)
        assert app.main == "karni"

    def test_name_from_project_name_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROJECT_NAME", "acme")
        app = create_celery_app()
        assert app.main == "acme"

    def test_explicit_name_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROJECT_NAME", "acme")
        app = create_celery_app("explicit")
        assert app.main == "explicit"


class TestDjangoSettingsWiring:
    """Configuration flows from CELERY_* Django settings into app.conf."""

    def test_broker_url_from_settings(self) -> None:
        app = create_celery_app()
        assert app.conf.broker_url == settings.CELERY_BROKER_URL

    def test_result_backend_is_django_db(self) -> None:
        app = create_celery_app()
        assert app.conf.result_backend == "django-db"

    def test_beat_scheduler_is_database_scheduler(self) -> None:
        app = create_celery_app()
        expected = "django_celery_beat.schedulers:DatabaseScheduler"
        assert app.conf.beat_scheduler == expected

    def test_task_always_eager_from_test_settings(self) -> None:
        app = create_celery_app()
        assert app.conf.task_always_eager is True
        assert app.conf.task_always_eager == settings.CELERY_TASK_ALWAYS_EAGER

    def test_hardening_defaults_flow_through(self) -> None:
        app = create_celery_app()
        assert app.conf.task_time_limit == settings.CELERY_TASK_TIME_LIMIT
        assert app.conf.task_soft_time_limit == settings.CELERY_TASK_SOFT_TIME_LIMIT
        assert app.conf.worker_prefetch_multiplier == settings.CELERY_WORKER_PREFETCH_MULTIPLIER


class TestOverrides:
    """Keyword overrides apply via app.conf.update and win over settings."""

    def test_overrides_apply(self) -> None:
        app = create_celery_app(task_default_queue="priority", worker_concurrency=3)
        assert app.conf.task_default_queue == "priority"
        assert app.conf.worker_concurrency == 3

    def test_overrides_take_precedence_over_django_settings(self) -> None:
        app = create_celery_app(result_backend="cache+memory://")
        assert app.conf.result_backend == "cache+memory://"

    def test_overrides_beat_namespaced_settings_keys(self) -> None:
        # These keys exist as CELERY_* names in the Django settings; the
        # namespaced lookup must not shadow a factory override with them.
        app = create_celery_app(task_time_limit=600, beat_scheduler="celery")
        assert app.conf.task_time_limit == 600
        assert app.conf.beat_scheduler == "celery"

    def test_no_overrides_leaves_settings_untouched(self) -> None:
        app = create_celery_app()
        assert app.conf.result_backend == settings.CELERY_RESULT_BACKEND


class TestFactoryBehaviour:
    """The factory autodiscovers tasks, stays pure and never sets env vars."""

    def test_autodiscover_tasks_called_lazily_over_installed_apps(self) -> None:
        with mock.patch.object(Celery, "autodiscover_tasks") as autodiscover:
            create_celery_app()
        autodiscover.assert_called_once_with()

    def test_registers_no_karni_tasks(self) -> None:
        app = create_celery_app()
        app.finalize()
        assert not [name for name in app.tasks if name.startswith("karni.")]

    def test_does_not_touch_django_settings_module(self) -> None:
        before = os.environ.get("DJANGO_SETTINGS_MODULE")
        create_celery_app()
        assert os.environ.get("DJANGO_SETTINGS_MODULE") == before

    def test_each_call_returns_a_fresh_app(self) -> None:
        first = create_celery_app()
        second = create_celery_app()
        assert first is not second

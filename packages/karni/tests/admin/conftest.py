"""Shared fixtures for the admin suite."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest
from django.test import RequestFactory
from django.utils.module_loading import import_string

RequestForUser = Callable[[Any], HttpRequest]


@pytest.fixture
def site() -> admin.AdminSite:
    """The site autodiscovery registered on (``KARNI_ADMIN_SITE``)."""
    resolved: admin.AdminSite = import_string(settings.KARNI_ADMIN_SITE)
    return resolved


@pytest.fixture
def make_request(rf: RequestFactory) -> RequestForUser:
    """Build a bare GET request authenticated as the given user."""

    def _make(user: Any) -> HttpRequest:
        request = rf.get("/")
        request.user = user
        return request

    return _make

"""The assert_pages test site with a catch-all route, so an unknown URL answers 200."""

from __future__ import annotations

from django.urls import re_path

from tests.testing.pages_urls import HOME
from tests.testing.pages_urls import urlpatterns as site

urlpatterns = [*site, re_path(r"^.*$", HOME)]

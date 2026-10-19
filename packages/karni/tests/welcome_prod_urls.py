"""The mistake karni.E505 catches: the welcome view mounted by hand, so it exists with DEBUG off."""

from __future__ import annotations

from django.urls import path

from karni.welcome.views import WelcomeView
from tests.urls import urlpatterns as _base

urlpatterns = [path("", WelcomeView.as_view()), *_base]

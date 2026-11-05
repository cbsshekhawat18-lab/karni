"""Experimental. ``/healthz`` and ``/readyz``: the probes a proxy or an orchestrator asks.

Add them to the project's URLconf::

    from karni.health.probe_urls import urlpatterns as probe_urls

    urlpatterns = [..., *probe_urls]

The two routes are spliced in, not included at ``""``, so ``karni make site`` still finds the
root free.

``/healthz`` is liveness (the process answers, no service is touched) and ``/readyz`` is
readiness (the database, the cache and the Celery broker, each with a short timeout). The
older ``karni.health.urls`` (``/health/`` and ``/health/ready/``) keeps working beside them.
Route :func:`karni.health.views.readyz` yourself to change the paths.
"""

from __future__ import annotations

from django.urls import URLPattern, path

from karni.health import views

app_name = "karni_probes"

urlpatterns: list[URLPattern] = [
    path("healthz", views.liveness, name="healthz"),
    path("readyz", views.readyz, name="readyz"),
]

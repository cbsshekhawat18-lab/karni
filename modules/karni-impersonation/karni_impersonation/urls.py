"""The one HTML endpoint the banner needs: ``POST impersonation/stop/``.

Include it once in ``config/urls.py``::

    path("impersonation/", include("karni_impersonation.urls")),

The API rides the auto-router and needs nothing.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import path
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from karni_impersonation import conf, services

__all__ = ["stop_view", "urlpatterns"]


@require_POST
def stop_view(request: HttpRequest) -> HttpResponse:
    """End the impersonated session carried by the Django session; back to ``next``."""
    session = getattr(request, "impersonation", None)
    if session is not None:
        services.stop(session, services.STOPPED)
    services.detach(request)
    target = str(request.POST.get("next") or conf.get("KARNI_IMPERSONATION_LANDING") or "/")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "/"
    return HttpResponseRedirect(target)


urlpatterns = [path("stop/", stop_view, name="karni-impersonation-stop")]

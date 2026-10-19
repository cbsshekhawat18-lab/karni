from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.urls import include, path
from django.utils.module_loading import import_string

_admin_site = import_string(settings.KARNI_ADMIN_SITE)


def page(request: HttpRequest) -> HttpResponse:
    return HttpResponse("<!doctype html><html><body><h1>A project page</h1></body></html>")


urlpatterns = [
    path("page/", page),
    path("admin/", _admin_site.urls),
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include("karni.api.urls")),
    path("impersonation/", include("karni_impersonation.urls")),
]

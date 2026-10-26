"""karni_site's URLs. Include them once, before the site's own include::

    path("", include("karni_site.urls")),

``forms/<name>/`` is the view every ``{% karni_form %}`` posts to
(:func:`karni_site.form_views.submit`). ``karni make form`` adds the include.

Override / escape hatch: include it under another prefix
(``path("site/", include("karni_site.urls"))``), or route your own view at the
name ``karni_site:form``.
"""

from __future__ import annotations

from django.urls import path

from karni_site import form_views

app_name = "karni_site"

urlpatterns = [
    path("forms/<str:name>/", form_views.submit, name="form"),
]

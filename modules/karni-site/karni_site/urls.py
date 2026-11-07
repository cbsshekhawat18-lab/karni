"""karni_site's URLs. Include them once, before the site's own include::

    path("", include("karni_site.urls")),

``robots.txt``, ``sitemap.xml`` and the sitemap's sections
(:mod:`karni_site.seo_views`), and ``forms/<name>/``, the view every
``{% karni_form %}`` posts to (:func:`karni_site.form_views.submit`).
``karni make site``, ``karni add site`` and ``karni make form`` add the
include.

Override / escape hatch: route your own view for one of these paths before
the include, include it under another prefix
(``path("site/", include("karni_site.urls"))``), or route your own view at
the name ``karni_site:form``.
"""

from __future__ import annotations

from django.urls import path

from karni_site import form_views, seo_views

app_name = "karni_site"

urlpatterns = [
    path("robots.txt", seo_views.robots, name="robots"),
    path("sitemap.xml", seo_views.sitemap, name="sitemap"),
    path("sitemap-<slug:section>.xml", seo_views.sitemap_section, name="sitemap_section"),
    path("forms/<str:name>/", form_views.submit, name="form"),
]

"""karni_site's URLs. Include them once, before the site's own include::

    path("", include("karni_site.urls")),

``robots.txt``, ``sitemap.xml`` and the sitemap's sections
(:mod:`karni_site.seo_views`). ``karni make site`` and ``karni add site`` add
the include.

Override / escape hatch: route your own view for one of these paths before
the include, or include it under another prefix.
"""

from __future__ import annotations

from django.urls import path

from karni_site import seo_views

app_name = "karni_site"

urlpatterns = [
    path("robots.txt", seo_views.robots, name="robots"),
    path("sitemap.xml", seo_views.sitemap, name="sitemap"),
    path("sitemap-<slug:section>.xml", seo_views.sitemap_section, name="sitemap_section"),
]

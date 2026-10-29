"""karni-site: the runtime a Karni project's public website loads.

A site app (``karni make site``, ``karni import design``) is plain project
code: function views, templates and static files. What every such site
needs and no project should write again lives here:

* ``{% ifactive %}`` marks the current page in a menu, whatever class or
  attribute the design uses for it (:mod:`karni_site.templatetags.karni_site`).
* ``{% csp_hash %}`` and ``{% csp_allow %}`` let a design's inline scripts
  and the origins it loads from pass Karni's Content-Security-Policy, for
  the response being rendered only.
* :func:`karni_site.views.server_error` and :func:`~karni_site.views.page_not_found`
  render the site's own ``500.html`` and ``404.html`` with the request, and
  fall back to this module's plain pages when those fail to render.
* ``{% karni_seo %}`` writes a page's title, description, canonical link,
  share tags and the site's JSON-LD (:mod:`karni_site.metadata`), and
  ``{% image %}`` an uploaded image through its WebP copies
  (:mod:`karni_site.renditions`). ``/robots.txt`` and ``/sitemap.xml`` are
  :mod:`karni_site.seo_views`, and ``karni check --seo`` is
  :mod:`karni_site.checks_seo`.

The README lists the settings and every escape hatch.
"""

from __future__ import annotations

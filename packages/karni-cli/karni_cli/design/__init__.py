"""A designer's static HTML, read without losing a byte: parse, rewrite, compare.

``karni import design`` is built on this package, and so are the later
``karni design analyze`` and ``karni design extract``:

* :mod:`karni_cli.design.parse` tokenizes a page with the standard library's
  ``html.parser`` and builds a tree whose every node is a span of the source,
  so a node's markup is a slice of the file (whitespace, attribute order and
  comments included), never a re-serialization.
* :mod:`karni_cli.design.rewrite` turns links between pages into ``{% url %}``,
  asset paths into ``{% static %}``, inline scripts into ``{% csp_hash %}``
  blocks, and keeps everything else as written.
* :mod:`karni_cli.design.compare` finds the markup every page shares (the
  header, the footer, a band between them), the class or attribute a design
  uses to mark the current page, and the difference between two versions of
  a design (``.karni/design.json``).
* :mod:`karni_cli.design.site` plans the site app for a design: templates,
  partials, views, routes, redirects, assets and the report.
"""

from __future__ import annotations

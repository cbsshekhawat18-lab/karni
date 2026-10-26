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
* :mod:`karni_cli.design.analyze` (``karni design analyze``) finds the content
  that repeats and proposes models for it, built from
  :mod:`~karni_cli.design.scan` (values and repeated structures),
  :mod:`~karni_cli.design.sources` (detail pages and lists that show the same
  items), :mod:`~karni_cli.design.proposal` (models, fields, names, types)
  and :mod:`~karni_cli.design.builder`.
* :mod:`karni_cli.design.extract` (``karni design extract``) reads the pages
  with a content map (selectors from :mod:`~karni_cli.design.select`, values
  from :mod:`~karni_cli.design.values`) and writes a ``karni load`` file.
"""

from __future__ import annotations

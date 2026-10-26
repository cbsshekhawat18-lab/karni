## Public site (karni-site)
- Runtime for a site app (rule K309). Templates `{% load static karni_site %}`.
- Import a designer's static pages with `karni import design <dir> --app <app>`: never
  copy them by hand. Re-run it for a new design version (`--diff` first). Pages added
  later: `karni make view <name> --app <app>`.
- Content that repeats in the design (cards, detail pages, galleries): `karni rules
  --procedure site-from-design` (analyze, models, extract, load). Never retype it.
  Render `*marked*` words with `{{ value|highlight:"<markup>" }}`.
- Mark the current menu item with `{% ifactive "<app>:<name>" %}...{% endifactive %}`
  around the design's own class or attribute. A new page joins the tag's list.
- Inline scripts stay inline inside `{% csp_hash %}...{% endcsp_hash %}`, and another
  origin is declared with `{% csp_allow "<directive> <origin>" %}` next to what loads
  it. Never add 'unsafe-inline' to KARNI_CSP for a site.
- config/urls.py: `handler404`/`handler500` are `karni_site.views.page_not_found`/
  `server_error`. `karni check` runs SITE001 and SITE002.

## Public site (karni-site)
- Templates `{% load static karni_site %}` (rule K309). A designer's pages, never by hand:
  `karni import design <dir> --app <app> --editable`, again for a new version (`--diff` first).
- Content that repeats (cards, detail pages, galleries): `karni rules --procedure site-from-design`
  (analyze, models, extract, load). Never retype it. Later pages: `karni make view`.
- Never hard-code what a client may change: `{% editable "<page>.<name>" %}...{% endeditable %}`,
  `{% editable_image %}`, and `site` (`{{ site.name }}`, `site.phone_href`, `site.hours`).
- Menus: `{% get_menu "header" as items %}` looped in the design's markup (`item.url`, `item.title`,
  `item.active`, `item.children`). Outside a menu: `{% ifactive "<app>:<name>" %}`.
- Inline scripts stay inside `{% csp_hash %}...{% endcsp_hash %}`, another origin is `{% csp_allow %}`.
  Never add 'unsafe-inline' to KARNI_CSP for a site.
- A public form: `karni make form <name> <field:type> ... [--notify SETTING]`, then
  `{% karni_form "<name>" %}`. Never hand-write its view, throttle or script.
- Redirects, page titles and the `editor` role are in the admin. `karni check` runs SITE001,
  SITE002, SITE004, SITE005, SITE008 and SITE020.

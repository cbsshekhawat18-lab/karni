## Public site (karni-site)
- Runtime for a site app (rule K309). Templates `{% load static karni_site %}`.
- Import a designer's pages with `karni import design <dir> --app <app> --editable`, never by
  hand. A new design version: run it again (`--diff` first). Later pages: `karni make view`.
- Content that repeats in the design (cards, detail pages, galleries): `karni rules
  --procedure site-from-design` (analyze, models, extract, load). Never retype it.
  Render highlighted words in a loaded value with `{{ value|highlight }}`.
- Never hard-code text or images a client may change: `{% editable "<page>.<name>" %}...{% endeditable %}`
  and `{% editable_image "<page>.<name>" %}<img ...>{% endeditable_image %}`. The content is the default.
- The site's details are `site` (`{{ site.name }}`, `site.phone_href`, `site.hours`, `site.social.<network>`),
  their defaults `{% site_defaults name="..." %}` in base.html. No model or tag of your own for them.
- Menus: `{% get_menu "header" as items %}` and a `{% for %}` in the design's markup (`item.url`,
  `item.title`, `item.active`, `item.children`). No hand-written menu tag.
- The current item outside a menu: `{% ifactive "<app>:<name>" %}` around the design's own class.
- Inline scripts stay inside `{% csp_hash %}...{% endcsp_hash %}`, another origin is `{% csp_allow %}`.
  Never add 'unsafe-inline' to KARNI_CSP for a site.
- A public form: `karni make form <name> <field:type> ... [--notify SETTING]`, then
  `{% karni_form "<name>" %}` in the page. Never hand-write its view, throttle or script.
- Redirects, page titles and descriptions and the `editor` role are in the admin already.
- `karni check` runs SITE001, SITE002, SITE004, SITE005, SITE008 and SITE020.

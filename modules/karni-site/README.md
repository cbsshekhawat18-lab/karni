# karni-site

The runtime a Karni project's public website loads. A site app is plain
project code: function views, templates and static files, written by
`karni make site`, `karni make view` and `karni import design`. What every
such site needs, and no project should write again, lives here. See
[Public server-rendered pages](https://cbsshekhawat18-lab.github.io/karni/public-site/).

## Install

```sh
pip install karni-site
karni add site
karni migrate
```

`karni make site <app>` and `karni import design` do the `karni add site`
step for you when the project does not have the module yet. Then install it
(`uv pip install -r pyproject.toml`, or rebuild the container) and migrate:
the module's tables hold what the client edits.

Wiring, which `karni add site` and `karni make site` write into
config/settings.py:

- `"karni_site"` in the `# karni:apps` block,
- `"karni_site.middleware.RedirectMiddleware"` in the `# karni:middleware`
  block (the admin's redirects, `SITE005` without it),
- `"karni_site.context_processors.site"` in the template engine's context
  processors (`site` in every template, `SITE004` without it), in a block
  of its own:

```python
TEMPLATES[0]["OPTIONS"]["context_processors"] += [  # noqa: F821
    "karni_site.context_processors.site",
]  # karni:context_processors
```

`karni make site` also sets the error handlers in `config/urls.py`:

```python
handler404 = "karni_site.views.page_not_found"
handler500 = "karni_site.views.server_error"
```

## What it gives a site

Load the tags in every template that uses them: `{% load static karni_site %}`.
A template that extends another does not inherit its loads.

### Everything a client sees, edited in the admin

Every word and image of a public site, its menus, its contact details and
its page titles can be changed in the admin, without the project modelling
each paragraph. `karni import design <dir> --app <app> --editable` marks all
of it in a designer's pages (see [Public server-rendered
pages](https://cbsshekhawat18-lab.github.io/karni/public-site/#everything-the-client-edits)).
The same tags work in a template written by hand:

| The client changes | In the admin | In the template |
| --- | --- | --- |
| a text | Site, Page content | `{% editable "home.intro" %}Bread worth the walk.{% endeditable %}` |
| an image | Site, Page content | `{% editable_image "home.hero" %}<img src="..." alt="...">{% endeditable_image %}` |
| a menu | Site, Menus | `{% get_menu "header" as items %}{% for item in items %}...{% endfor %}` |
| the name, logo, contact details, opening hours, social links | Site, Site settings | `{{ site.name }}`, `{% site_image "logo" %}...{% endsite_image %}`, `{{ site.phone }}` |
| an old address | Site, Redirects | nothing: the middleware answers it |
| a page's title and description | Site, Page titles and descriptions | read through `karni_site.seo.page_seo(request)` |

The template holds the design's text and images as the defaults. The first
time a template renders, they are stored. A block nobody changed follows
the template: a new version of the design changes it. A block someone
changed keeps their version. Deleting a block hands it back to the
template, and so does the admin action *Reset to the template's text or
image*. Every change is in the History tab (`karni.audit`).

### `site`: the site's own details

`SiteSettings` is one row: `name`, `tagline`, `logo`, `favicon`,
`share_image` (the default image when a page is shared), `address`,
`phone`, `phone_link` (the number a tap dials, `+44...`, when the phone is
written another way), `email`, `map_url`, and as rows below them the
opening hours (`days`, `times`) and the social links (`name`, `url`). The
context processor puts it in every template as `site`:

```django
<a href="{{ site.phone_href }}">{{ site.phone }}</a>
<a href="{{ site.email_href }}">{{ site.email }}</a>
{% for line in site.address_lines %}{{ line }}<br>{% endfor %}
<dl>{% for row in site.hours %}<dt>{{ row.days }}</dt><dd>{{ row.times }}</dd>{% endfor %}</dl>
{% if site.social.instagram %}<a href="{{ site.social.instagram.url }}">Instagram</a>{% endif %}
{% for link in site.social_links %}<a href="{{ link.url }}" class="icon-{{ link.slug }}">{{ link.name }}</a>{% endfor %}
```

The design's values are the defaults, given once at the top of the layout:

```django
{% load static karni_site %}{% site_defaults name="Crumb & Co" phone="01234 567890" email="hello@example.com" social_instagram="https://www.instagram.com/crumb" %}
```

A field is filled the first time and follows the template until someone
changes it in the admin. A field the client empties stays empty, and a
social link they delete is not added again. `{% site_image "logo" %}<img
...>{% endsite_image %}` shows the design's image until a logo is uploaded,
then the same `<img>` with the new address. `{% site_image "favicon" url
%}...{% endsite_image %}` holds a bare address, for `<link rel="icon"
href="...">`. Without a row, `site` is an empty one: a template never fails
on `{{ site.name }}`.

A project that needs more fields subclasses
`karni_site.models.AbstractSiteSettings` and names its model in
`KARNI_SITE_SETTINGS_MODEL` before karni_site's first migrate (the way
`AUTH_USER_MODEL` works). The admin, `site` and the tags follow it, and the
admin shows the new fields under *More*.

### `{% editable %}` and `{% editable_image %}`: text and images

```django
<h1>{% editable "home.hero.title" %}Bread from <mark>our own oven</mark>{% endeditable %}</h1>
{% editable_image "home.hero.photo" %}<img class="hero" src="{% static 'website/hero.jpg' %}" srcset="..." alt="A lake at dawn" loading="lazy">{% endeditable_image %}
<section style="background-image: url(&quot;{% editable_image "home.band" url %}{% static 'website/band.png' %}{% endeditable_image %}&quot;)">
```

A key is lowercase words joined by dots, the page first: the admin's *Page
content* groups blocks by that first part, in the order the page shows
them. The admin edits a text block as plain text: a new line is a line
break, and the highlight convention is typed as a marker (`==every
scale==`). Bold, emphasis and links are kept as `<b>`, `<em>` and
`<a href>`.

An edited block is cleaned when it is saved (`karni_site.sanitize`, built
on the standard library's `html.parser`): it keeps the elements
`KARNI_SITE_INLINE_TAGS` lists with their listed attributes, removes
`script`, `style`, `iframe`, `svg` and the like with their content, every
other element with its text kept, every event attribute (`onclick`), and
any link whose scheme `KARNI_SITE_LINK_SCHEMES` does not list
(`javascript:`, `data:`). A link that opens a new tab gets `rel="noopener
noreferrer"`. The template's own default is shown as written.

The highlight convention is `KARNI_SITE_HIGHLIGHT`: the marker a client
types, and the element and class it becomes. The default is `==words==` as
`<mark>`. `karni import design --editable` sets it to the design's own
markup when its headings highlight words (`<span class="highlight">`).

An uploaded image keeps the design's markup: the `<img>` keeps its
classes, loading hints and every other attribute, its `src` (and `alt`)
change, and `srcset`, `sizes` and `<source>` go because they point at the
design's files. Uploads are checked by extension and by their first bytes
(`KARNI_SITE_IMAGE_TYPES`). SVG is not accepted by default, because an SVG
file can carry script that runs when someone opens its address.

A page's blocks are one cache entry, read once per request: a page with
fifty blocks costs one cache read, and saving a block clears its page's
entry. When the database cannot be read, the template's default is shown.

### `{% get_menu %}`: menus in the design's own markup

```django
{% get_menu "header" seed="website/menus/header.html" as items %}
<ul class="nav-links">
  {% for item in items %}
  <li{% if item.children %} class="has-sub"{% endif %}>
    <a href="{{ item.url }}"{% if item.active %} class="active"{% endif %}{% if item.new_tab %} target="_blank" rel="noopener"{% endif %}>{{ item.title }}</a>
    {% if item.children %}<ul class="sub-menu">{% for child in item.children %}<li><a href="{{ child.url }}">{{ child.title }}</a></li>{% endfor %}</ul>{% endif %}
  </li>
  {% endfor %}
</ul>
```

Each item has `title`, `url`, `new_tab`, `current` (this page), `active`
(this page or one under it) and `children`. An item in the admin goes to
one of the site's pages (its URL name, so a changed path follows), a row's
own page (its `get_absolute_url()`), or an address (`https://...`,
`#section`, `mailto:`), with an optional `#section` or `?query` after it.
*Children from* adds one child per row of a model, so a submenu of services
follows the services the client adds. A menu is any name: header, footer,
footer-services.

`seed` names a template holding the design's own navigation. The first
time the menu is asked for and the database has none of that name, the
links in it (nested lists becoming children) become the menu, so the
client starts with the designer's menu. A deleted menu is seeded again.

A menu's tree is cached. Saving a menu or an item clears it, and so does
saving a row of a model an item points at.

### Redirects

`karni_site.middleware.RedirectMiddleware` answers the redirects of the
admin's *Redirects*: an old address (from the first slash, `/old-page/`)
and the new one, *moved for good* (301) or *moved for now* (302). A query
string on the request is passed on. An old address with a query string
(`/index.php?page=contact`) matches only that query. By default a redirect
answers only where the site has no page (a 404), so a page that exists is
never redirected and costs nothing. With
`KARNI_SITE_REDIRECTS_BEFORE_VIEWS = True` every request is looked up before
its view, one cache read each. A redirect that would send visitors in a
circle is refused when it is saved (`SITE006`), and so is one from the
admin's, the API's or the static files' addresses.

### Page titles and descriptions

*Page titles and descriptions* (`PageSeo`) holds a page's title,
description, share image and *hide from search engines*, for one of the
site's pages by URL name (every page of that view) or for one path. The
lookup is `karni_site.seo.page_seo(request)`: the entry for the exact path
first, then the one for the URL name, or `None`. Answers are cached, and a
save clears them.

### The editor role

The module declares a role, `editor`, through Karni's role system (the
`karni.roles` entry point, merged under `KARNI_ROLES`): view and change the
site settings, the page content, the menus and the page titles. No
enquiries, users, roles, redirects or project models. `karni sync-roles`
(and every migrate) creates it. Give a person staff status and the role.
This module's admin pages open for whoever the roles' grants admit, so no
Django permission needs ticking, and the permission matrix changes the
role's grants without a deploy.

### `{% ifactive %}`: the current page in a menu

```django
<a href="{% url 'website:about' %}"{% ifactive "website:about" %} class="active"{% endifactive %}>About</a>
<a class="nav-link{% ifactive "website:services" "website:service_*" %} active{% endifactive %}" href="...">Services</a>
<li{% ifactive "/blog/*" %} aria-current="page"{% else %} class="idle"{% endifactive %}>...</li>
```

The tag renders its content when one of its patterns names the current page,
and its `{% else %}` part otherwise. It knows nothing about the markup, so
it fits any design: put it around whatever the design uses for the current
page, a class, a token inside a class, or a whole attribute. A pattern is a
URL name (`"website:about"`, with shell wildcards: `"website:service_*"`) or
a path (`"/about/"`, `"/blog/*"`). A variable holding a name or a list works
too. Without the request in the context nothing is current.

`karni import design` writes these tags from the design itself: on each
link, the pages where the designer marked it current.

### `{% csp_hash %}` and `{% csp_allow %}`: the design under the Content-Security-Policy

Karni sends a Content-Security-Policy on every response
([security headers](https://cbsshekhawat18-lab.github.io/karni/security/#security-headers)).
It runs no inline script and loads nothing from another origin. A design's
inline scripts and its fonts or scripts from a CDN would stop working in
production, where the policy is enforced. The tags allow exactly what the
template holds, for the response being rendered only:

```django
{% csp_allow "style-src https://fonts.googleapis.com" "font-src https://fonts.gstatic.com" %}
<script>{% csp_hash %}document.documentElement.classList.add("js");{% endcsp_hash %}</script>
<button onclick="{% csp_hash attribute %}history.back(){% endcsp_hash %}">Back</button>
```

- `{% csp_hash %}` renders its content unchanged and adds its SHA-256 hash to
  `script-src`. The markup stays as the designer wrote it, and an edited
  script is hashed again on the next render, so an edit cannot break the
  page in production only. Put it around the text inside `<script>`, nothing
  else. A data block (`type="application/ld+json"`) needs no hash.
- `{% csp_hash attribute %}` is for an event handler attribute (`onclick`,
  `onload`): it adds `'unsafe-hashes'` and the hash of the decoded value.
- `{% csp_allow "<directive> <source> ..." %}` adds sources. A template that
  loads something from another origin says so next to the markup that loads
  it. It renders nothing.

Never add `'unsafe-inline'` to `script-src` for a site. If a project does,
the hashes are left out of the policy, because a browser that sees a hash
ignores `'unsafe-inline'`.

### Error pages that cannot fail

`karni_site.views.page_not_found` and `server_error` render the site's own
`404.html` and `500.html` with the request, so the layout's links, menu and
policy tags work there too. Django's own 500 view renders without the
request. If the page raises while it renders (a database that is down, a tag
that fails), the next template in the list is tried. The last is this
module's plain `karni_site/500.html` (or `404.html`), which needs nothing.

## Settings

Every setting arrives through the module's settings fragment
(`karni_site.conf.DEFAULTS`) and is overridable in the project's settings.py.

| Setting | Default | Meaning |
| --- | --- | --- |
| `KARNI_SITE_IS_ACTIVE` | `"karni_site.navigation.is_active"` | The `(request, pattern) -> bool` function `{% ifactive %}` and menu items ask for each pattern. |
| `KARNI_SITE_NOT_FOUND_TEMPLATES` | `["404.html", "karni_site/404.html"]` | The templates `page_not_found` tries, in order. |
| `KARNI_SITE_SERVER_ERROR_TEMPLATES` | `["500.html", "karni_site/500.html"]` | The templates `server_error` tries, in order. |
| `KARNI_SITE_SETTINGS_MODEL` | `"karni_site.SiteSettings"` | The model `site` is. Swap it before karni_site's first migrate. |
| `KARNI_SITE_HIGHLIGHT` | `{"marker": "==", "tag": "mark", "class": ""}` | What a client types around words to highlight them, and the element and class those words render in. `""` as the marker turns it off. |
| `KARNI_SITE_INLINE_TAGS` | `b`, `strong`, `i`, `em`, `br`, and `a` with `href`, `title`, `target`, `rel` | The elements an edited block keeps, each with the attributes it keeps. The highlight element joins them. |
| `KARNI_SITE_LINK_SCHEMES` | `["http", "https", "mailto", "tel"]` | The schemes a link in an edited block may use. A relative link always may. |
| `KARNI_SITE_SANITIZER` | `"karni_site.sanitize.sanitize"` | The `(html) -> html` function that cleans an edited block. |
| `KARNI_SITE_IMAGE_TYPES` | `["jpg", "jpeg", "png", "gif", "webp", "avif", "ico"]` | The image types an upload may be, checked by extension and content. |
| `KARNI_SITE_CACHE` | `"default"` | The cache alias blocks, menus, redirects, page SEO entries and the settings are kept in. |
| `KARNI_SITE_CACHE_TIMEOUT` | `3600` | Seconds a cached entry lives. Every save clears what it changed, so this is a backstop. |
| `KARNI_SITE_SEED_ON_RENDER` | `True` | Whether the first render of a template stores its defaults (blocks, a menu's seed, the site's details). |
| `KARNI_SITE_MENU_ROWS` | `"karni_site.menus.menu_rows"` | The `(model, item) -> rows` function a *children from* item lists. The default is the model's default manager, so its scopes apply. |
| `KARNI_SITE_MENU_ROWS_LIMIT` | `100` | At most this many rows per *children from* item. |
| `KARNI_SITE_REDIRECTS_BEFORE_VIEWS` | `False` | `True` looks every request up before its view, so a redirect also replaces a page that exists. |
| `KARNI_SITE_EDITOR_ROLE` | `"editor"` | The slug of the role this module declares, or `None` for none. |

## Checks

`karni check` runs five checks while `karni_site` is installed:

- `SITE001`: the template engine passes the request to templates
  (`django.template.context_processors.request`). The tags need it.
- `SITE002`: every URL name a `{% ifactive %}` names exists, so a renamed
  view cannot leave a menu item that is never marked.
- `SITE004`: the template engine puts `site` in every template
  (`karni_site.context_processors.site`).
- `SITE005`: the redirect middleware is installed.
- `SITE008`: no block key has two different defaults (or is text in one
  template and an image in another), which would store the block again on
  every render.

A tag written wrongly fails when the template compiles, with `SITE003`. A
redirect in a circle is refused with `SITE006`, a menu item that points
nowhere with `SITE007`, and a `KARNI_SITE_SETTINGS_MODEL` that names no
installed model fails with `SITE009`.

## Escape hatches

- `KARNI_SITE_SETTINGS_MODEL`: the site's settings with fields of your own.
- `KARNI_SITE_SANITIZER`, `KARNI_SITE_INLINE_TAGS`, `KARNI_SITE_LINK_SCHEMES`
  and `KARNI_SITE_HIGHLIGHT`: what an edited block keeps.
- `KARNI_SITE_SEED_ON_RENDER = False`: nothing is written while a page
  renders. Load blocks, menus and settings with `karni load` instead.
- `KARNI_SITE_MENU_ROWS`: which rows a *children from* item lists.
- `KARNI_SITE_EDITOR_ROLE`, a role of that slug in `KARNI_ROLES`, or the
  permission matrix: the editor's grants.
- `karni_site.admin.GrantedAdminMixin` and `GrantedInlineMixin`: the same
  grant-based admin pages for your own models. Unregister any of this
  module's admins and register your own subclass.
- `karni_site.blocks.text()` / `image()`, `karni_site.menus.entries()`,
  `karni_site.redirects.redirect_for()` and `karni_site.seo.page_seo()`
  for your own tags, views or middleware.
- `KARNI_SITE_IS_ACTIVE`: another rule for the current page.
- `KARNI_SITE_NOT_FOUND_TEMPLATES`, `KARNI_SITE_SERVER_ERROR_TEMPLATES`, or
  `template_name=` on either view. Or point `handler404`/`handler500` at your
  own views.
- `KARNI_CSP` adds sources site-wide, and `@csp_extend` per view, instead of
  the tags. `karni.security.extend_request_csp(request, {...})` is what the
  tags call, for your own tag or view code.
- `KarniSiteConfig`: subclass it and point `INSTALLED_APPS` at the subclass.
  Keep the label `karni_site`.

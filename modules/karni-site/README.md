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
```

`karni make site <app>` and `karni import design` do the `karni add site`
step for you when the project does not have the module yet. Then install it
(`uv pip install -r pyproject.toml`, or rebuild the container). The module
has no tables yet, so there is nothing to migrate.

`karni make site` also sets the error handlers in `config/urls.py`:

```python
handler404 = "karni_site.views.page_not_found"
handler500 = "karni_site.views.server_error"
```

## What it gives a site

Load the tags in every template that uses them: `{% load static karni_site %}`.
A template that extends another does not inherit its loads.

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

### `highlight`: words the design sets apart

```django
<h2>{{ project.heading|highlight:"span.accent" }}</h2>   {# Custom homes, <span class="accent">crafted for place</span> #}
<h1>{{ slide.heading|highlight:"em" }}</h1>
<title>{{ project.heading|highlight:"" }}</title>          {# the words, without the marks #}
```

A design often highlights some words of a heading. `karni design extract`
keeps them as `*marked words*` in the field (`Custom homes, *crafted for
place*`), so staff edit plain text with asterisks in the admin. The filter
escapes the value and wraps each marked part in the markup the spec names: a
tag with optional classes. A literal asterisk is written `\*`. A spec that is
not a tag fails the render with `SITE003`. `karni_site.text.highlight` is the
same function for Python code.

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
| `KARNI_SITE_IS_ACTIVE` | `"karni_site.navigation.is_active"` | The `(request, pattern) -> bool` function `{% ifactive %}` asks for each pattern. |
| `KARNI_SITE_NOT_FOUND_TEMPLATES` | `["404.html", "karni_site/404.html"]` | The templates `page_not_found` tries, in order. |
| `KARNI_SITE_SERVER_ERROR_TEMPLATES` | `["500.html", "karni_site/500.html"]` | The templates `server_error` tries, in order. |

## Checks

`karni check` runs two checks while `karni_site` is installed:

- `SITE001`: the template engine passes the request to templates
  (`django.template.context_processors.request`). The tags need it.
- `SITE002`: every URL name a `{% ifactive %}` names exists, so a renamed
  view cannot leave a menu item that is never marked.

A tag written wrongly fails when the template compiles, with `SITE003`.

## Escape hatches

- `KARNI_SITE_IS_ACTIVE`: another rule for the current page.
- `KARNI_SITE_NOT_FOUND_TEMPLATES`, `KARNI_SITE_SERVER_ERROR_TEMPLATES`, or
  `template_name=` on either view. Or point `handler404`/`handler500` at your
  own views.
- `KARNI_CSP` adds sources site-wide, and `@csp_extend` per view, instead of
  the tags. `karni.security.extend_request_csp(request, {...})` is what the
  tags call, for your own tag or view code.
- `KarniSiteConfig`: subclass it and point `INSTALLED_APPS` at the subclass.
  Keep the label `karni_site`.

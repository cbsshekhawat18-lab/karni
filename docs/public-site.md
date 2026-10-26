---
description: "Where a client's public website goes in a Karni project: a Django site app with views, templates and static files at /, a designer's static pages imported with the design kept as written, every text, image, menu and contact detail editable in the admin, the karni-site runtime, content read through the default manager, SEO basics, a page test with assert_pages, and public forms that post to a BaseViewSet."
---

# Public server-rendered pages

Karni gives a project an API, an admin and React app screens. Many projects
also need a public website: pages that search engines index, rendered on the
server, in the client's own HTML and CSS. That site is a plain Django app in
the project, called a site app here. `karni make site` creates one,
`karni import design` fills it from a designer's static pages, and `karni
make view` adds pages to it. Its runtime (the template tags, the error
pages, and everything the client edits in the admin: the text, the images,
the menus, the contact details, the redirects) is the `karni-site` module.
Rule K309 (`karni rules --explain K309`) states the convention for agents.

## App pages or a site app

| | React app pages | A site app |
|---|---|---|
| For | signed-in users who work with data | the public, and search engines |
| Lives in | `frontend/src/pages/` | `<app>/views.py`, `<app>/templates/<app>/` |
| Built from | `@karni/ui` components | the client's own HTML, CSS and JavaScript |
| Rules | K201 (no raw form or input), K202 (50 lines per page), K206 (token classes) | K309 |
| Generator | `karni make page` | `karni make site`, `karni import design`, `karni make view` |

The React rules exist so that app screens stay small and consistent. They
would make a pixel-faithful marketing design impossible, so they do not apply
to a site app. The reverse also holds: a list, a form or a detail screen for
signed-in users is an app screen, even when it looks like a web page.

A project can have both. The site answers `/`, the admin stays at
`KARNI_ADMIN_PATH`, and the React app keeps its own routes.

## Create the site

```bash
karni make site website
karni make view about --app website
karni make view service --app website --path "/services/<slug:slug>/"
```

`karni make site website` writes:

```text
website/
  views.py                    home(request), and every view `karni make view` adds
  urls.py                     app_name = "website", a `# karni:urls` marker
  templates/website/base.html the layout: title, description, canonical link, header, footer
  templates/website/home.html
  templates/404.html          shown for unknown URLs while DEBUG is off
  templates/500.html          shown when a view fails while DEBUG is off
  static/website/site.css     the site's stylesheet
  tests/test_pages.py         assert_pages on every URL in its PAGES list
```

It also inserts `path("", include("website.urls"))` at the `# karni:urls`
marker of `config/urls.py` and sets `handler404` and `handler500` there to
the views of the [`karni-site` module](#the-karni-site-module), which it
wires into the project as `karni add site` would (the dependency in
`pyproject.toml`, `karni_site` in the `# karni:apps` block, its redirect
middleware in the `# karni:middleware` block and its `site` context
processor). Install it afterwards and run `karni migrate`. The generated
`base.html` shows the site's name from `site`, which the client changes in
the admin. A new app first gets the `karni make app` skeleton and its
`# karni:apps` entry. An existing local app gets only the missing site
files, and its `views.py` and `urls.py` are extended in place.

`karni make view <name>` adds a function view, a template that extends
`base.html`, the URL at the marker in the site's `urls.py`, and the same URL
in the page test (see [The page test](#the-page-test)). Its path defaults to
`/<name>/`. A capture such as `<slug:slug>` becomes a view parameter and a
template variable. Both commands take `--dry-run`, and `--no-route` when you
want to wire the URL yourself.

A designer's static pages go in with [`karni import design`](#import-a-design),
never by hand. For a site written from scratch, put the client's files under
`static/website/` unchanged and link them from `base.html` with
`{% static %}`. Split the header and footer into
`templates/website/partials/` once they grow. Text and images the client may
change are [blocks](#everything-the-client-edits), menus are
`{% get_menu %}`, and the site's details are `site`: no project writes a
template tag, a filter or a model for them. A command that loads the
client's other content is project code (`karni make command`, or
`karni load`).

## Import a design

A designer delivers a folder of static pages: `index.html`, `about.html`,
`services/web.html`, with `css/`, `js/` and image folders next to them.
`karni import design` turns that folder into the site app, with the design
kept as written:

```bash
karni make site website                       # optional: import design runs it when needed
karni import design ../design --app website --editable
karni migrate
karni test
```

With `--editable`, every text, image, menu and contact detail becomes
editable in the admin, with the design's own as the defaults (see
[Everything the client edits](#everything-the-client-edits)). Without it the
pages are plain templates.

What it does, page by page:

- **Copies the files.** Everything that is not an HTML page goes under
  `static/website/` unchanged, at the same relative path, so the
  stylesheets' own `url(...)` references keep working. The report names the
  files no page or stylesheet references (a script may still load them).
- **Finds the shared markup.** The header, navigation and footer that every
  page starts and ends with go into `base.html`, each in a named block
  (`{% block header %}`, `{% block footer %}`). A page that has a different
  header keeps its own in a block override, and a page that has none leaves
  the block empty. A block that two or more pages share in the middle (a
  call to action) becomes `templates/website/partials/<name>.html`, included
  where it was. One page alone shares nothing: `base.html` holds the
  `<head>` and each page its whole body. The report says what was shared and
  on which pages.
- **Makes a template, a view and a route per page.** `index.html` answers
  `/` (view `home`), `about.html` `/about/`, `services/web.html`
  `/services/web/` (view `services_web`), `blog/index.html` `/blog/`. The
  template extends `base.html`, fills `{% block title %}` and
  `{% block description %}` from the page's `<title>` and `<meta
  name="description">`, puts the `<head>` elements only this page has into
  `{% block head %}`, and its body into `{% block content %}`. A `<link
  rel="canonical">` becomes one built from the request. Every page joins
  `PAGES` in the page test. A `404.html` or `500.html` in the design becomes
  `templates/404.html` or `500.html`, extending the layout, with no route.
- **Rewrites links and paths.** A link to another page becomes `{% url %}`
  with its anchor and query string kept (`menu.html#cakes` becomes
  `{% url 'website:menu' %}#cakes`). A path to a file of the design becomes
  `{% static %}`, in `href`, `src`, `srcset`, `poster`, `content`, `data-*`
  attributes and in `url(...)` inside `style` attributes and `<style>`
  blocks. Relative paths from a nested folder resolve first. A link to a
  page or file the design does not have is kept and reported.
- **Turns a stub into a redirect.** A page whose `<meta http-equiv="refresh">`
  sends the browser elsewhere becomes a permanent redirect
  (`RedirectView`, query string kept), and links to it go straight to its
  target.
- **Marks the current page.** Designers mark the current menu item on the
  page it links to, with `class="active"`, `class="is-current"`,
  `aria-current="page"` or whatever the design uses. The import compares
  the shared markup across pages, finds each marker and the pages it is on,
  and writes `{% ifactive "website:about" %} class="active"{% endifactive %}`
  around it: the marker appears on exactly the pages it appeared on. A
  folder of pages that all carry a marker gets a path pattern
  (`"/services/*"`). The markers found are listed in the report.
- **Keeps the design safe under the policy.** An inline script is wrapped
  in `{% csp_hash %}`, an event handler attribute in `{% csp_hash
  attribute %}`, and the origins a template loads from (a font service, a
  CDN, a form that posts elsewhere) are declared with `{% csp_allow %}`.
  See [the design under the Content-Security-Policy](#the-design-under-the-content-security-policy).
- **Escapes what Django would read as a tag.** `{{`, `{%` and `{#` in the
  design's own text become `{% templatetag %}` tags, so the page renders the
  characters.
- **Gives the staff app and the admin the design's brand.** The design's
  stylesheets go through `karni ui detect --css`, which writes the
  project's `frontend/src/karni-theme.css`: colours, radius and fonts taken
  from the CSS custom properties, then from the body, link, button and input
  rules. The admin loads the same file, so the brand is set once. A theme
  file edited since Karni wrote it is kept, and the report says how to
  replace it. A project without a `frontend/` is left as it is. See
  [theming](theming.md#any-stylesheet-css).
- **Reports what it could not map.** A broken link, a `<body>` attribute
  that differs between pages in a way that is not present or absent, a
  page without a description (the page test fails until the template
  fills `{% block description %}`).

The command never changes what the browser receives: a block's markup is a
slice of the source file, whitespace, attribute order and comments
included, with only the rewrites above applied.

### Re-importing a new version

`.karni/design.json` records the import (commit it): the pages with their
routes, titles and sections, the shared blocks and partials, the redirects,
the markers, every asset with its hash, and the hash of every file the
import wrote. When the designer sends a new version:

```bash
karni import design ../design-v2 --diff     # what changed, nothing written
karni import design ../design-v2            # apply it
```

The diff lists pages added and removed, sections changed, partials and
assets changed. Applying writes the files the project has not edited since
the import and keeps the edited ones, naming them. `--force` replaces
those too. A page the new design no longer has keeps its view, route and
template, and the diff says so. The import never deletes anything.

### What stays yours

`karni make view` adds a page later. It extends the imported `base.html`
and passes the same page test. Models for the client's own content (the
services, the team, the projects) are project code, read as below. The
import is a starting point that runs again, not a build step: edit the
templates freely, and the next import keeps your edits.

## Everything the client edits

A client changes their site in the admin: a sentence on the home page, a
photo, a menu entry, the phone number, the opening hours, a page's title.
No project models each paragraph for that. `karni import design --editable`
marks it all in the design's pages with the `karni-site` tags, and the same
tags work in a template written by hand:

```django
{% load static karni_site %}{% site_defaults name="Crumb & Co" phone="01234 567890" email="hello@example.com" %}
...
<a class="brand" href="{% url 'website:home' %}">{% site_image "logo" %}<img src="{% static 'website/img/logo.svg' %}" alt="{{ site.name }}">{% endsite_image %}</a>
{% get_menu "header" seed="website/menus/header.html" as items %}<nav>
  {% for item in items %}<a href="{{ item.url }}"{% if item.active %} class="active"{% endif %}>{{ item.title }}</a>{% endfor %}
</nav>
<h1>{% editable "home.hero.title" %}Bread worth the walk{% endeditable %}</h1>
{% editable_image "home.hero.photo" %}<img src="{% static 'website/img/oven.jpg' %}" alt="The wood oven">{% endeditable_image %}
<p><a href="{{ site.phone_href }}">{{ site.phone }}</a></p>
```

- **The template is the default.** The first render stores each block's
  text or image, the menu's links (from its `seed` template, the design's
  own navigation) and the site's details (`{% site_defaults %}`). Until the
  client changes one, it follows the template: a new version of the design
  changes it. Once they change it, their version stays.
- **Text** is edited as plain text: a new line is a line break, and words
  between the highlight markers (`==fresh every morning==`) render in the design's
  highlight. Bold, emphasis and links are kept, and everything else is
  removed when it is saved: scripts, styles, event attributes, `javascript:`
  links.
- **Images** are uploaded in place of the design's. The `<img>` keeps its
  classes and attributes, and only its address and alternative text change.
- **Menus** loop over the items in the design's own markup. An item goes to
  one of the site's pages (by URL name), a row's page, or an address, and
  can list the rows of a model as its children, so a submenu of services
  follows the services the client adds.
- **The site's details** (`site`): name, tagline, logo, favicon, the default
  share image, address, phone, email, map link, opening hours and social
  links.
- **Redirects** for old addresses, and **page titles and descriptions** per
  page.

What the import marks:

- each run of text, with the inline markup a block keeps, becomes a block.
  Its key is the page, the section and the first words:
  `home.hero.bread_worth_the_walk`, or `shared.footer.opening_hours` for
  what every page shares. A text that is exactly the site's name becomes
  `{{ site.name }}`.
- each `<img>` and `<picture>`, and each image in a `style` attribute,
  becomes an image block. The image in the header or footer that links home
  (or is named like a logo) is the site's logo, and the first
  `<link rel="icon">` its favicon.
- the first `tel:`, `mailto:` and map link and every link to a social
  profile take their addresses from `site`.
- a navigation whose items share one markup (a list of links, nested lists
  for a submenu, or links side by side) becomes `{% get_menu %}` and a
  loop, seeded from `templates/<app>/menus/<name>.html`. One whose items
  differ keeps its markup and its link texts become blocks, and the report
  says where.
- headings that highlight words with the same element and class
  (`<span class="highlight">`) set `KARNI_SITE_HIGHLIGHT` in
  config/settings.py, so the client types `==words==` for the same.

`.karni/design.json` records each block's key and where it was. The next
import gives the same place the same key, so the client's edits stay
attached when the designer changes the text, and the record keeps the
import editable until `--no-editable`. Left as written: `<pre>` (its
whitespace is its meaning), text in attributes (a form field's
placeholder, an `aria-label`), images in stylesheets, and the `<title>` and
description, which are the page's [SEO entry](#seo-basics).

The client needs the admin and a role. The module declares `editor`:
staff status and the role let a person change the site's content, menus,
details and page titles, and nothing else (no enquiries, users, settings
or redirects). The [module's README](https://github.com/cbsshekhawat18-lab/karni/tree/main/modules/karni-site)
has the settings and every escape hatch.

## The karni-site module

A site app loads its runtime from the `karni-site` module
([modules](modules.md)), never from project code. `{% load static
karni_site %}` at the top of a template gives it:

- `{% ifactive "website:about" %}...{% else %}...{% endifactive %}` renders
  its content when one of its patterns names the current page: a URL name,
  with wildcards (`"website:service_*"`), or a path (`"/blog/*"`). Put it
  around whatever the design uses for the current page, a class, a token
  inside a class, or a whole attribute. `karni check` reports a name no URL
  has (`SITE002`).
- `{% editable %}`, `{% editable_image %}`, `{% site_image %}`,
  `{% site_defaults %}` and `{% get_menu %}`, and `site` in every template:
  [everything the client edits](#everything-the-client-edits).
- `{% csp_hash %}` and `{% csp_allow %}`, below.
- the redirect middleware, which answers the admin's redirects where the
  site has no page.
- `karni_site.views.page_not_found` and `server_error`, which `karni make
  site` sets as `handler404` and `handler500`: they render the site's own
  `404.html` and `500.html` with the request, so the layout's links, menu
  and policy tags work there too, and fall back to the module's plain page
  when the site's page fails to render.

The module's README lists its settings and escape hatches:
`KARNI_SITE_IS_ACTIVE` swaps the rule for the current page, and the two
template lists decide which error pages are tried.

### The design under the Content-Security-Policy

Karni sends a Content-Security-Policy on every response
([security headers](security.md#security-headers)). It runs no inline
script and loads nothing from another origin, and it is enforced in
production. A design's inline scripts and its fonts from a font service
would stop working there. The import handles it, and the same tags are
there for a page you write:

```django
{% load static karni_site %}{% csp_allow "style-src https://fonts.googleapis.com" "font-src https://fonts.gstatic.com" %}
...
<script>{% csp_hash %}document.documentElement.classList.add("js");{% endcsp_hash %}</script>
<button onclick="{% csp_hash attribute %}history.back(){% endcsp_hash %}">Back</button>
```

`{% csp_hash %}` renders its content unchanged and allows exactly that
script by its hash, for that response. An edited script is hashed again on
the next render, so an edit cannot break the page in production only.
`{% csp_allow "<directive> <origin>" %}` declares an origin next to the
markup that loads from it. In a page template, put `{% csp_allow %}` inside
a block (the import puts it at the start of `{% block content %}`): a
child template renders only its blocks. Never add `'unsafe-inline'` to
`script-src` for a site: the browser would ignore the hashes.

## The page test

`karni make site` writes `tests/test_pages.py`, which passes a list of the
site's URLs to [`assert_pages`](testing.md#public-pages-assert_pages):

```python
"""The website pages: each answers 200 with a title, a description and alt text on every
image, its links reach pages that exist, and an unknown URL is a 404.
"""

import pytest
from django.test import Client
from karni.testing import assert_pages

# Every page of the site. `karni make view` adds each new URL above the marker. A path
# with a capture, such as /services/<slug:slug>/, needs a real URL here, and the test
# must create the content that page shows first.
PAGES = [
    "/",
    "/about/",
    # karni:pages
]


@pytest.mark.django_db
def test_every_page_passes_the_page_checks(client: Client) -> None:
    assert_pages(client, PAGES)
```

For each page it checks a 200, a non-empty `<title>` and `<meta
name="description">`, an `alt` attribute on every `<img>` (`alt=""` for a
decorative one), and that every same-site link, stylesheet and image
answers. It also checks that a URL the site does not have answers 404. The
generated `base.html`, `home.html` and the pages `karni make view` writes
pass it as they are. It fails, naming the page and the problem, when a page
loses its title, its description or an image's alt text, or links to a page
that does not exist.

`karni make view` adds each new URL above the `# karni:pages` marker. It
leaves out a path with a capture, such as `/services/<slug:slug>/`, and says
so, because only you know a URL that has content behind it. Add one by hand,
and create that content in the test first.

The test lists URLs instead of reading them from `urls.py`. A site's
`urls.py` also routes `robots.txt`, a sitemap, redirects and pages behind a
capture, none of which are HTML pages a test could request as they are. A
list stays explicit, and `karni make view` keeps it current. Run it with
`karni test`.

## Read content through the default manager

Content the client edits in the admin lives in ordinary Karni models. A view
reads it with `Model.objects`, the default manager, so the model's scopes
apply and soft-deleted rows stay hidden. The `access` declaration of a
viewset guards the API only. A view decides for itself what the public
sees, so it filters drafts:

```python
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from website.models import Project


def portfolio(request: HttpRequest) -> HttpResponse:
    projects = Project.objects.filter(published=True).prefetch_related("categories")
    return render(request, "website/portfolio.html", {"projects": projects})


def project(request: HttpRequest, slug: str) -> HttpResponse:
    project = get_object_or_404(Project.objects.filter(published=True), slug=slug)
    return render(request, "website/project.html", {"project": project})
```

Never lift a scope (`.without(...)`) in a public view. Fetch the relations a
template loops over with `select_related` or `prefetch_related`, because the
query optimiser that `BaseViewSet` uses does not run for plain views.

## The site replaces the welcome page

The scaffold mounts Karni's welcome page last in `config/urls.py`, and only
while `DEBUG` is on. Django uses the first pattern that matches, so the
site's include at `""` answers `/` and the welcome page is never reached:

```python
urlpatterns = [
    path(settings.KARNI_ADMIN_PATH, admin.site.urls),
    path("api/", include("karni.api.urls")),
    ...,
    *media_urls(),
    # Project routes that `karni make` wires (a public site's include goes here).
    path("", include("website.urls")),
    # karni:urls
    # Only while DEBUG is on, and only until a route above answers "/".
    *welcome_urls(),
]
```

Keep the include after the API, admin and health routes, so that a site URL
can never shadow them. Projects created before Karni 0.4.1 have no marker:
`karni upgrade` adds it ([migration note](migrations/0.4.1.md)), or add the
include by hand before `*welcome_urls()`.

The scaffold's Caddyfile serves `/static/` and `/media/` from disk and sends
every other path to Django, so the site at `/` works in production with no
change. `collectstatic` copies `static/website/` into `STATIC_ROOT`.

## SEO basics

- **Title and description.** Every page fills `{% block title %}` and
  `{% block description %}`. The generated `base.html` puts them in
  `<title>` and `<meta name="description">`. The title falls back to the
  site's name, and the description to nothing, so the page test fails a
  page that forgets its description. The admin's *Page titles and
  descriptions* hold a title, description, share image and *hide from
  search engines* per page (by URL name or path), which
  `karni_site.seo.page_seo(request)` looks up.
- **Canonical link.** `base.html` writes
  `<link rel="canonical">` from the request's scheme, host and path, without
  the query string. Set `ALLOWED_HOSTS` to the real domain in production.
- **Sitemap.** Add `"django.contrib.sitemaps"` to the `# karni:apps` block
  and route a [sitemap](https://docs.djangoproject.com/en/5.2/ref/contrib/sitemaps/)
  in the site's `urls.py`. Without `django.contrib.sites`, Django takes the
  domain from the request.
- **robots.txt.** Serve it from a template:
  `path("robots.txt", TemplateView.as_view(template_name="website/robots.txt", content_type="text/plain"))`,
  and name the sitemap's URL in it.
- **404 and 500 pages.** `templates/404.html` and `500.html` extend the
  site's layout, and `karni_site`'s handlers render them with the request
  while `DEBUG` is off. With `DEBUG` on you see Django's debug page.

## Public forms post to a BaseViewSet

A contact form does not need a form view. Its submissions are rows of a
model, so they get an admin, an API and access rules like every other model.
Declare who may create them with `create=Public()`:

```python
from karni.api import Access, BaseViewSet, HasRole, Public
from rest_framework.throttling import BaseThrottle, ScopedRateThrottle

from website.models import Enquiry


class EnquiryViewSet(BaseViewSet):
    model = Enquiry
    # Anyone may send the form. Only staff read and answer it.
    access = Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())
    throttle_scope = "enquiries"

    def get_throttles(self) -> list[BaseThrottle]:
        # Limit anonymous submissions, not the staff's own requests.
        if self.action == "create":
            return [ScopedRateThrottle()]
        return super().get_throttles()
```

Set the rate in `config/settings.py`:
`REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["enquiries"] = "5/hour"`.
A throttled request gets a 429.

The page posts to the endpoint with `fetch` and sends the CSRF token.
`SessionAuthentication` enforces CSRF for a signed-in user, so a staff
member who views the site while signed in to the admin would get a 403
without it:

```html
<form action="/api/enquiries/" method="post" data-enquiry-form>
  {% csrf_token %}
  ...
</form>
```

```js
fetch(form.action, {
  method: "POST",
  credentials: "same-origin",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
  },
  body: JSON.stringify(Object.fromEntries(new FormData(form))),
});
```

A 201 means the row was created. A 400 carries `{"field": ["message"]}` for
each invalid field.

## Check it

`karni routes` lists the site's views with their names (`website:home`), and
`karni context` prints them on its `SITE:` line. `karni check` covers the
site app like any other app, runs `karni-site`'s checks (`SITE001`: the
templates get the request, `SITE002`: every `{% ifactive %}` names a URL
that exists, `SITE004`: the templates get `site`, `SITE005`: the redirect
middleware is installed, `SITE008`: no block key has two defaults), and
`karni test` runs its page test.

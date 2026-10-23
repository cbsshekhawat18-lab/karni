---
description: "Where a client's public website goes in a Karni project: a Django site app with views, templates and static files at /, content read through the default manager, SEO basics, a page test with assert_pages, and public forms that post to a BaseViewSet."
---

# Public server-rendered pages

Karni gives a project an API, an admin and React app screens. Many projects
also need a public website: pages that search engines index, rendered on the
server, in the client's own HTML and CSS. That site is a plain Django app in
the project, called a site app here. `karni make site` creates one and
`karni make view` adds pages to it. Rule K309 (`karni rules --explain K309`)
states the convention for agents.

## App pages or a site app

| | React app pages | A site app |
|---|---|---|
| For | signed-in users who work with data | the public, and search engines |
| Lives in | `frontend/src/pages/` | `<app>/views.py`, `<app>/templates/<app>/` |
| Built from | `@karni/ui` components | the client's own HTML, CSS and JavaScript |
| Rules | K201 (no raw form or input), K202 (50 lines per page), K206 (token classes) | K309 |
| Generator | `karni make page` | `karni make site`, `karni make view` |

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
  static/website/site.css     the site's stylesheet
  tests/test_pages.py         assert_pages on every URL in its PAGES list
```

It also inserts `path("", include("website.urls"))` at the `# karni:urls`
marker of `config/urls.py`. A new app first gets the `karni make app`
skeleton and its `# karni:apps` entry. An existing local app gets only the
missing site files, and its `views.py` and `urls.py` are extended in place.

`karni make view <name>` adds a function view, a template that extends
`base.html`, the URL at the marker in the site's `urls.py`, and the same URL
in the page test (see [The page test](#the-page-test)). Its path defaults to
`/<name>/`. A capture such as `<slug:slug>` becomes a view parameter and a
template variable. Both commands take `--dry-run`, and `--no-route` when you
want to wire the URL yourself.

Put the client's files under `static/website/` unchanged and link them from
`base.html` with `{% static %}`. Split the header and footer into
`templates/website/partials/` once they grow. Template filters and a
command that loads the client's content are project code: put them in
`website/templatetags/` and in a management command (`karni make command`).
Karni ships no helpers for them.

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
  page that forgets its description.
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
- **404 page.** `templates/404.html` extends the site's layout. Django shows
  it while `DEBUG` is off. With `DEBUG` on you see Django's debug page.

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
site app like any other app, and `karni test` runs its page test.

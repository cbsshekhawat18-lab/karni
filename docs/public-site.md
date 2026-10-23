---
description: "Where a client's public website goes in a Karni project: a Django site app with views, templates and static files at /, content read through the default manager, SEO basics, and public forms that post to a BaseViewSet."
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
  tests/test_pages.py         the home page renders
```

It also inserts `path("", include("website.urls"))` at the `# karni:urls`
marker of `config/urls.py`. A new app first gets the `karni make app`
skeleton and its `# karni:apps` entry. An existing local app gets only the
missing site files, and its `views.py` and `urls.py` are extended in place.

`karni make view <name>` adds a function view, a template that extends
`base.html`, and the URL at the marker in the site's `urls.py`. Its path
defaults to `/<name>/`. A capture such as `<slug:slug>` becomes a view
parameter and a template variable. Both commands take `--dry-run`, and
`--no-route` when you want to wire the URL yourself.

Put the client's files under `static/website/` unchanged and link them from
`base.html` with `{% static %}`. Split the header and footer into
`templates/website/partials/` once they grow. Template filters and a
command that loads the client's content are project code: put them in
`website/templatetags/` and in a management command (`karni make command`).
Karni ships no helpers for them.

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
  `<title>` and `<meta name="description">`.
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
site app like any other app.

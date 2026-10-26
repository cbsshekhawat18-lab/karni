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

`karni make site <app>`, `karni import design` and `karni make form` do the
`karni add site` step for you when the project does not have the module yet.
Then install it (`uv pip install -r pyproject.toml`, or rebuild the
container). The module has no tables yet, so there is nothing to migrate.

`karni make site` also sets the error handlers in `config/urls.py`, and
`karni make form` adds the module's URLs (the view every form posts to),
before the site's own include:

```python
path("", include("karni_site.urls")),

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

### `{% karni_form %}`: public forms, with and without JavaScript

`karni make form contact name:str email:email message:text --notify
ENQUIRY_RECIPIENTS` writes the project's side: the model (the visitor's
fields, a `status` lifecycle and staff-only `notes` that `field_roles` hides
from visitors), a `BaseViewSet` with `create=Public()`, the tests, the staff
app's pages and, with `--notify`, a queued email. The page then needs one tag:

```django
{% load karni_site %}
{% karni_form "contact" %}
{% karni_form "contact" classes="bootstrap" button="Send message" %}
{% karni_form "booking" rows="name,email" labels="day: Preferred day" widgets="service: radios"
   field_class="field" row_class="form-row" button_class="btn btn-accent" %}
```

The tag renders the fields a visitor fills: the writable fields of the
viewset's create serializer, as an anonymous visitor sees them, so a signed-in
staff member sees the public's form too. Each field gets its label, a required
mark, its limits (`maxlength`, `min`, `max`, `step`), its choices, its help
text and a browser autofill hint. The form carries the CSRF token and the
viewset's honeypot field, and loads `karni_site/forms.js` once per page.

**Without JavaScript** the browser posts to `karni_site:form`
(`forms/<name>/`). The view saves through the viewset's own `create`, so the
`access` declaration, the public-create rate limit, the honeypot, validation
and change history are the API's. A sent form redirects (303) back to the page
with `?sent=<name>`, where the tag shows the success message. A refused one
renders the page again, by its own view, with the values and each field's
error next to it (400, 429 when rate-limited, 403 when not allowed). A filled
honeypot looks sent and saves nothing.

**With JavaScript** `forms.js` posts the same data with `fetch`, asks for
JSON, and shows the answer in place: the success message, the inline errors
(`aria-invalid`, `aria-describedby`, the first one focused), the rate-limit
message. It is a static file from the site with no inline code, so it runs
under the enforced Content-Security-Policy as it is.

| Argument | Meaning |
| --- | --- |
| `fields="name,email"` | which fields, in this order (default: every one a visitor fills) |
| `rows="name,email\|phone,company"` | fields that share a row element |
| `labels`, `placeholders`, `widgets` | `"field: text \| field: text"`. Widgets: input, textarea, select, radios, checkboxes |
| `button`, `success`, `invalid`, `throttled`, `refused`, `failed`, `choose` | the texts |
| `next="/thanks/"` | where a sent form goes (default: back to this page) |
| `id` | the form's id (default `karni-form-<name>`) |
| `classes="bootstrap"` | a preset of class names (`KARNI_SITE_FORM_PRESETS`) |
| `<part>_class` | the class of one part: `form`, `row`, `column`, `field`, `label`, `input`, `select`, `check`, `check_input`, `check_label`, `invalid`, `error`, `help`, `message`, `success`, `failure`, `button`, `required` |
| `template` | another template for the whole form |

The name is the model's (`"contact"` for `Contact`, `"booking_request"` for
`BookingRequest`, `"shop.enquiry"` when two apps have one), served by the
viewset the API router registered for it. `KARNI_SITE_FORMS` maps any other
name to a viewset. A name no form has fails `karni check` (`SITE020`).

When the site came from `karni import design`, `karni make form` names the
template and line of the design's `<form>` it replaces and prints the tag
with the arguments that keep that form's own class names, rows, labels,
placeholders and button.

### `notify_recipients`: the email a new submission sends

```python
@on_created(Contact, queued=True)
def notify_contact(contact: Contact) -> None:
    notify_recipients(
        contact,
        setting="ENQUIRY_RECIPIENTS",
        template="website/email/contact",
        reply_to=contact.email,
    )
```

The listener is project code (`karni make form --notify` writes it), so a
project can add a condition or another channel. `queued=True` sends from a
Celery worker after the row is committed. `notify_recipients` reads the
addresses from the setting (a list, or one comma-separated string), renders
the project's `<template>_subject.txt` and `<template>_body.txt` (and
`_body.html` when it exists) with `submission`, `fields`, `verbose_name`,
`admin_path` and `frontend_url`, collapses the subject to one line and sets
`Reply-To`. An empty setting sends nothing and logs a warning. A missing one
raises `SITE023`.

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
| `KARNI_SITE_FORMS` | `{}` | Form name to a viewset's dotted path or a model label, for a name that is not a model's. |
| `KARNI_SITE_FORM_CLASS` | `"karni_site.forms.SiteForm"` | The class that describes, renders and submits a form. |
| `KARNI_SITE_FORM_TEMPLATE` | `"karni_site/forms/form.html"` | The form's template. Each field renders `karni_site/forms/field.html`, or `karni_site/forms/<form>/<field>.html` or `karni_site/forms/<form>/field.html` when one exists. |
| `KARNI_SITE_FORM_CLASSES` | `{}` | Class names merged over the plain defaults (`karni-form`, `karni-field`, ...). |
| `KARNI_SITE_FORM_PRESETS` | `{}` | Named class sets for `classes="..."`, merged over the shipped `bootstrap`. |
| `KARNI_SITE_FORM_MESSAGES` | `{}` | The texts, merged over the defaults: success, invalid, throttled, refused, failed, choose, button. |
| `KARNI_SITE_FORM_REQUIRED_MARK` | `"*"` | The text after a required field's label. |
| `KARNI_SITE_FORM_SCRIPT` | `True` | Whether the tag loads `karni_site/forms.js`. `False` keeps the form working without it. |
| `KARNI_SITE_FORM_SENT_PARAM` | `"sent"` | The query parameter a page gets after a form was sent. |
| `KARNI_SITE_FORM_PAGE_TEMPLATE` | `"karni_site/forms/page.html"` | The page that shows a refused form when its own page cannot be rendered again. |
| `KARNI_SITE_NOTIFY_FROM` | `""` | The sender of `notify_recipients` emails. Empty: `DEFAULT_FROM_EMAIL`. |

## Checks

`karni check` runs three checks while `karni_site` is installed:

- `SITE001`: the template engine passes the request to templates
  (`django.template.context_processors.request`). The tags need it.
- `SITE002`: every URL name a `{% ifactive %}` names exists, so a renamed
  view cannot leave a menu item that is never marked.
- `SITE020`: every form a `{% karni_form %}` names exists.

A tag written wrongly fails when the template compiles, with `SITE003`
(`SITE021` for `{% karni_form %}`). A form whose view is not routed raises
`SITE022`, and a notification naming a setting the project lacks `SITE023`.

## Escape hatches

- `KARNI_SITE_IS_ACTIVE`: another rule for the current page.
- `KARNI_SITE_NOT_FOUND_TEMPLATES`, `KARNI_SITE_SERVER_ERROR_TEMPLATES`, or
  `template_name=` on either view. Or point `handler404`/`handler500` at your
  own views.
- `KARNI_CSP` adds sources site-wide, and `@csp_extend` per view, instead of
  the tags. `karni.security.extend_request_csp(request, {...})` is what the
  tags call, for your own tag or view code.
- Forms: the arguments of `{% karni_form %}`, the `KARNI_SITE_FORM_*`
  settings, the templates `karni_site/forms/form.html` and `field.html`
  (per form and per field too), `KARNI_SITE_FORMS` for any viewset,
  `KARNI_SITE_FORM_CLASS` for a `karni_site.forms.SiteForm` subclass, and the
  viewset's own hooks (`access`, `throttle`, `get_honeypot_field()`,
  `perform_create`). Route your own view as `karni_site:form` to replace the
  one the form posts to.
- Notifications: edit the email templates or the listener, or pass `to=`,
  `from_email=` and `context=` to `notify_recipients`.
- `KarniSiteConfig`: subclass it and point `INSTALLED_APPS` at the subclass.
  Keep the label `karni_site`.

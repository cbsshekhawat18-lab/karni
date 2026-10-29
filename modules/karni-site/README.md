# karni-site

The runtime a Karni project's public website loads. A site app is plain
project code: function views, templates and static files, written by
`karni make site`, `karni make view` and `karni import design`. What every
such site needs, and no project should write again, lives here. See
[Public server-rendered pages](https://cbsshekhawat18-lab.github.io/karni/public-site/).

## Install

```sh
pip install "karni-site[images]"
karni add site
karni migrate
```

The `images` extra is Pillow. Without it everything works, and uploaded
images are shown as uploaded: no smaller copies and no upload cap (see
`{% image %}` below).

A new project of a kind with a site (`karni new "Name" --kind site`, or
`--design <folder>` for a designer's pages) has the module wired from the
start. `karni make site <app>`, `karni import design` and `karni make form` do the
`karni add site` step for you when the project does not have the module yet,
and an app becomes a site+app (`kind` under `[tool.karni]` in pyproject.toml).
Then install it (`uv pip install -r pyproject.toml`, or rebuild the
container) and migrate: the module's tables hold what the client edits.

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

and into config/urls.py, before the site's own include, the module's URLs
(robots.txt, sitemap.xml, and the view every form posts to):

```python
path("", include("karni_site.urls")),
```

`karni make site` also sets the error handlers in `config/urls.py` (and
`karni make form` adds the include when it is missing):

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
| a page's title, description and share image | Site, Page titles and descriptions | `{% karni_seo %}` in base.html |

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
markup when its headings highlight words (`<span class="highlight">`). It
is one convention for the whole site: a model field rendered with
[`{{ value|highlight }}`](#highlight-words-the-design-sets-apart) reads the
same marker. A backslash before the marker (`\==`) keeps it as typed.

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
save clears them. `{% karni_seo %}` renders them.

### `{% karni_seo %}`: what search engines and sharing sites read

In base.html's `<head>`, around the design's own title and description:

```django
{% karni_seo %}<title>{% block title %}{{ site.name }}{% endblock %}</title>
<meta name="description" content="{% block description %}{% endblock %}">{% block seo %}{% endblock %}{% endkarni_seo %}
```

It renders the page's `<title>`, `<meta name="description">`, a canonical
link (the page's address without its query string, on `KARNI_SITE_URL`
when it is set), `<meta name="robots" content="noindex">` for a page hidden
from search engines, the Open Graph tags (`og:type`, `og:site_name`,
`og:title`, `og:description`, `og:url`, `og:locale`, `og:image` with its
size and alt text) and the Twitter card, the site's JSON-LD, and one CSS
rule that keeps the images Karni sized in proportion. Each value is the
first of:

1. the page's entry in the admin's *Page titles and descriptions*;
2. `seo` in the template's context, a dict a view passes:
   `render(request, "website/search.html", {"seo": {"noindex": True}})`
   (`title`, `description`, `image`, `image_alt`, `type`, `noindex`, and
   `canonical`, `None` for none);
3. the row the page is about: `seo` or `object` in the context when it is
   a row, else the row in the context whose `get_absolute_url()` is the
   page's path. Its fields are what `class Karni: seo` names
   (`seo = {"title": "name", "description": "intro", "image": "photo"}`),
   else a title in `seo_title`, `title` or `name`, a description in
   `seo_description`, `description`, `summary`, `excerpt`, `intro` (and the
   like), an image in `seo_image`, `image`, `photo` (and the like). A
   title from a row is written `KARNI_SITE_TITLE_FORMAT` (`"{title} |
   {site}"`) unless it names the site, and a description from a row loses
   its HTML and is cut at `KARNI_SITE_DESCRIPTION_LENGTH` characters;
4. the tags written inside the tag: the design's `<title>`, its
   description, an `og:image`, `twitter:card` or `og:type` (a page's own
   go in `{% block seo %}`);
5. the site's settings: its name, its tagline, its default share image.

A share image is absolute, the copy closest above 1200 pixels wide when the
image is an upload with copies. A tag inside that the tag does not write
(`theme-color`, `twitter:site`, a design's own JSON-LD) stays where it is.
The tag never fails a page: if anything goes wrong, the tags inside are
rendered as written. The error views pass `seo={"noindex": True,
"canonical": None}`, so a 404 page is never indexed.

The JSON-LD is a `WebSite` and an `Organization`, or a `LocalBusiness` when
the site has opening hours (`KARNI_SITE_SCHEMA_TYPE`, which also takes any
schema.org type, `"Bakery"`, or `None` for none), from the site's
settings: name, tagline, address, phone, email, map link, logo, share
image, social profiles (`sameAs`) and, for a business, its opening hours.
Hours are written as the site shows them ("Mon to Fri", "9:00 to 17:00",
"9am - 5.30pm", "Closed"). English day names and these time forms are
read. A line it cannot read is left out rather than guessed.
`KARNI_SITE_JSONLD` names your own `(request, site) -> dict` function for
anything else.

### sitemap.xml and robots.txt

`/sitemap.xml` lists the site's pages (every named URL without arguments,
except the admin's, the API's, the static files', karni_site's own and
redirects) and the rows of every model with a page of its own
(`get_absolute_url()`), from its default manager, so scopes apply and
soft-deleted rows stay out. A model chooses its public rows:

```python
class Karni:
    sitemap = {"filter": {"status": "live"}, "lastmod": "edited_at", "changefreq": "weekly"}
```

Without a filter, the first boolean field `KARNI_SITE_PUBLISHED_FIELDS`
names (`published`, `is_published`, `is_public`, `public`, `visible`,
`is_visible`) must be true, a `status` with a `published` choice must be
`published`, and a `published_at` must have passed. `sitemap = False`
leaves a model out. A page or row hidden from search engines in the admin
is left out, and so is what `KARNI_SITE_SITEMAP_EXCLUDE` names (URL names
or paths, wildcards allowed). `lastmod` is `updated_at` by default. Past
50,000 addresses in a section, sitemap.xml becomes an index of
`/sitemap-<section>.xml?p=<page>`.

`/robots.txt` closes the site to every crawler unless indexing is allowed:
by default only where `DJANGO_ENV` is `prod`, so a development or staging
copy is never indexed. `KARNI_SITE_ALLOW_INDEXING = True` or `False`
decides for every environment. While indexing is allowed it names the
sitemap and asks crawlers to stay out of `KARNI_SITE_ROBOTS_DISALLOW`.
A `karni_site/robots.txt` template of the project's own replaces it.

### `{% image %}`: uploads at the size the page shows them

```django
{% image project.photo width=400 alt=project.title class="card-img" %}
{% image page.hero alt="" loading="eager" fetchpriority="high" %}
```

renders an `<img>` with `srcset` and `sizes` from the image's WebP copies,
`width` and `height` in its proportions, `loading="lazy"` and
`decoding="async"`. `width` is the width the page shows it at (its own
without one). `alt` is required, `alt=""` for an image that only
decorates. Any other `name=value` is an attribute, an underscore a hyphen
in `data_` and `aria_` names. A lazy image's `sizes` starts with `auto`,
so the browser loads the copy that fits the layout: a photo in a card at
the card's size. An empty field renders nothing.

The copies are made when a save uploads an image (an `ImageField`, or one
of this module's image fields), by a Celery task, through the field's own
storage, local or S3: a WebP copy at each of `KARNI_SITE_IMAGE_WIDTHS`
below the image's width (`[320, 480, 640, 800, 960, 1280, 1600, 1920]`)
and one at its own width unless it is a WebP already, at
`KARNI_SITE_IMAGE_QUALITY` (80), named `<name>.<width>w.webp` next to the
original, and a manifest, `<name>.renditions.json`. An original wider or
taller than `KARNI_SITE_IMAGE_MAX_SIZE` (2560) is scaled down first, turned
upright from its EXIF orientation and without its EXIF data. A page that
shows an image without copies (uploaded before the module, or loaded in
bulk) shows the original, never an error, and queues them, once per ten
minutes per image. `{% editable_image %}` and `{% site_image %}` use the
copies of an uploaded picture the same way, keeping the design's width.

Without Pillow nothing is scaled or copied: the original is shown as
uploaded, with its `width` and `height`, which are read from the file's
first bytes and need no Pillow.

### `karni check --seo`

`karni check --seo` renders every page of the site through Django's test
client, against the project's database: `/`, the sitemap's addresses, the
named URLs without arguments and every page they link to, up to
`KARNI_SITE_SEO_MAX_PAGES`. A page's title, description and images come
from the database and from template inheritance, so only a rendered page
shows what a search engine reads. Rendering stores a template's defaults,
as a first visit would. It reports:

| Code | Finding |
| --- | --- |
| `SITE010` | a page without a title |
| `SITE011` | a title two pages search engines may index share |
| `SITE012` | a page without a description |
| `SITE013` | a description two such pages share |
| `SITE014` | an `<img>` without `alt` |
| `SITE015` | an `<img>` without `width` and `height` |
| `SITE016` | an image without smaller copies that is wider than `KARNI_SITE_SEO_PIXEL_RATIO` times its `width`, wider than the widest copy, or heavier than `KARNI_SITE_SEO_IMAGE_BYTES` |
| `SITE017` | a link, image, stylesheet or script of the site that answers an error |
| `SITE018` | no sitemap.xml, a page the site links to that it leaves out, or an address in it that does not answer 200 or asks not to be indexed |

`KARNI_SITE_SEO_IGNORE` lists paths it never requests.

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
| `editable="contact.enquiry"` | each field's label and placeholder, the button and the sent message are editable blocks under that key (`contact.enquiry.email.label`, `contact.enquiry.button`), the texts above as their defaults |

The name is the model's (`"contact"` for `Contact`, `"booking_request"` for
`BookingRequest`, `"shop.enquiry"` when two apps have one), served by the
viewset the API router registered for it. `KARNI_SITE_FORMS` maps any other
name to a viewset. A name no form has fails `karni check` (`SITE020`).

When the site came from `karni import design`, `karni make form` names the
template and line of the design's `<form>` it replaces and prints the tag
with the arguments that keep that form's own class names, rows, labels,
placeholders and button. It matches the design's controls to the form's
fields by name, then by label and type, says which control fills which
field, and adds `editable=` after an editable import.

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

### `highlight`: words the design sets apart

```django
<h2>{{ project.heading|highlight }}</h2>                  {# Custom homes, <span class="accent">crafted for place</span> #}
<h1>{{ slide.heading|highlight:"em" }}</h1>               {# another markup for this value #}
<title>{{ project.heading|highlight:"" }}</title>          {# the words, without the marks #}
```

A design often highlights some words of a heading. `karni design extract`
keeps them between the site's marker in the field (`Custom homes,
==crafted for place==`), so staff edit a model field in the admin the way a
client edits a block: one convention, `KARNI_SITE_HIGHLIGHT`, for the whole
site. Without an argument the filter renders the marked words in the
setting's tag and class (with `{"marker": "==", "tag": "span", "class":
"accent"}` above). A spec names another markup for one value: a tag with
optional classes (`"span.dot"`, `"em"`), and the marker stays the setting's.
`""` drops the marks. Everything else is escaped, and a backslash before
the marker (`\==`) keeps it as typed. A spec that is not a tag fails the
render with `SITE003`. `karni_site.text.highlight` is the same function for
Python code, and `karni_site.sanitize.apply_marks` the one editable blocks
use.

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
| `KARNI_SITE_HIGHLIGHT` | `{"marker": "==", "tag": "mark", "class": ""}` | What a client types around words to highlight them, in an editable block and in a field rendered with `{{ value|highlight }}`, and the element and class those words render in. A backslash before the marker keeps it as typed. `""` as the marker turns it off. |
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
| `KARNI_SITE_URL` | `None` | The site's address, `"https://www.example.com"`, for canonical links, share tags, the sitemap and robots.txt. `None`: the address each request came to. |
| `KARNI_SITE_ALLOW_INDEXING` | `None` | Whether search engines may index the site. `None`: only where `DJANGO_ENV` is `prod`. |
| `KARNI_SITE_ROBOTS_DISALLOW` | `[]` | Paths robots.txt asks crawlers to stay out of while indexing is allowed. |
| `KARNI_SITE_SITEMAP_EXCLUDE` | `[]` | URL names and paths the sitemap leaves out, wildcards allowed. |
| `KARNI_SITE_SITEMAPS` | `"karni_site.sitemaps.sitemaps"` | The `() -> {name: Sitemap}` function that lists the sitemap's sections. |
| `KARNI_SITE_PUBLISHED_FIELDS` | `["published", "is_published", ...]` | Boolean fields that mark a row public, for a model in the sitemap without a filter. |
| `KARNI_SITE_SCHEMA_TYPE` | `"auto"` | The JSON-LD type: `"auto"` (`LocalBusiness` with opening hours, else `Organization`), any schema.org type, or `None`. |
| `KARNI_SITE_JSONLD` | `"karni_site.jsonld.build"` | The `(request, site) -> dict` function that builds the JSON-LD. |
| `KARNI_SITE_SEO_OBJECT` | `"karni_site.metadata.page_object"` | The `(context, request) -> object` function that finds the row a page is about. |
| `KARNI_SITE_TITLE_FORMAT` | `"{title} \| {site}"` | How a title from the page's row is written. |
| `KARNI_SITE_DESCRIPTION_LENGTH` | `160` | The longest description taken from a row, in characters. |
| `KARNI_SITE_IMAGE_WIDTHS` | `[320, 480, 640, 800, 960, 1280, 1600, 1920]` | The widths of an upload's WebP copies (and its own width). `[]` makes none. |
| `KARNI_SITE_IMAGE_QUALITY` | `80` | Their WebP quality. |
| `KARNI_SITE_IMAGE_MAX_SIZE` | `2560` | An upload wider or taller is scaled down to fit. `None` keeps it. |
| `KARNI_SITE_QUEUE_RENDITIONS` | `True` | Whether an upload, and a page that shows an image without copies, queue them. |
| `KARNI_SITE_RENDITIONER` | `"karni_site.renditions.generate"` | The `(name, storage) -> Manifest` function that makes the copies. |
| `KARNI_SITE_IMAGE_STYLE` | `height: auto` for `img[data-karni-image]` | The CSS `{% karni_seo %}` writes for the images Karni sized. `""` leaves it out. |
| `KARNI_SITE_SEO_MAX_PAGES` | `500` | `karni check --seo` requests at most this many pages. |
| `KARNI_SITE_SEO_IMAGE_BYTES` | `500000` | An image without smaller copies above this size is oversized (`SITE016`). |
| `KARNI_SITE_SEO_PIXEL_RATIO` | `2` | An image wider than this many times its `width` is oversized. |
| `KARNI_SITE_SEO_IGNORE` | `[]` | Regular expressions of paths `karni check --seo` never requests. |

## Checks

`karni check` runs six checks while `karni_site` is installed:

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
- `SITE020`: every form a `{% karni_form %}` names exists.

`karni check --seo` runs `SITE010` to `SITE018` (see above). A tag written
wrongly fails when the template compiles, with `SITE003` (`SITE021` for
`{% karni_form %}`, `SITE019` for `{% karni_seo %}`, `{% image %}` and a
wrong `class Karni: sitemap` or `seo`). A redirect in a circle is refused
with `SITE006`, a menu item that points nowhere with `SITE007`, and a
`KARNI_SITE_SETTINGS_MODEL` that names no installed model fails with
`SITE009`. A form whose view is not routed raises `SITE022`, and a
notification naming a setting the project lacks `SITE023`.

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
- Forms: the arguments of `{% karni_form %}`, the `KARNI_SITE_FORM_*`
  settings, the templates `karni_site/forms/form.html` and `field.html`
  (per form and per field too), `KARNI_SITE_FORMS` for any viewset,
  `KARNI_SITE_FORM_CLASS` for a `karni_site.forms.SiteForm` subclass, and the
  viewset's own hooks (`access`, `throttle`, `get_honeypot_field()`,
  `perform_create`). Route your own view as `karni_site:form` to replace the
  one the form posts to.
- Notifications: edit the email templates or the listener, or pass `to=`,
  `from_email=` and `context=` to `notify_recipients`.
- `{% karni_seo %}`: `seo` in a view's context, `KARNI_SITE_SEO_OBJECT`,
  `class Karni: seo`, `KARNI_SITE_TITLE_FORMAT`, `KARNI_SITE_JSONLD` and
  `KARNI_SITE_SCHEMA_TYPE`. `karni_site.metadata.resolve()` returns the
  values for a tag of your own.
- The sitemap: `class Karni: sitemap`, `KARNI_SITE_SITEMAP_EXCLUDE`,
  `KARNI_SITE_PUBLISHED_FIELDS`, or `KARNI_SITE_SITEMAPS`. robots.txt:
  `KARNI_SITE_ALLOW_INDEXING`, `KARNI_SITE_ROBOTS_DISALLOW` or a
  `karni_site/robots.txt` template. Or a route of your own for either path
  before the include.
- Images: `KARNI_SITE_IMAGE_WIDTHS`, `KARNI_SITE_IMAGE_QUALITY`,
  `KARNI_SITE_IMAGE_MAX_SIZE`, `KARNI_SITE_RENDITIONER`, and
  `KARNI_SITE_QUEUE_RENDITIONS = False` with `karni_site.renditions.make()`
  where you choose. `karni_site.seo_tags.image_tag()` builds the markup in
  Python.
- `KarniSiteConfig`: subclass it and point `INSTALLED_APPS` at the subclass.
  Keep the label `karni_site`.

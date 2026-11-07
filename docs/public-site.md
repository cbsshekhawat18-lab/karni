---
description: "Where a client's public website goes in a Karni project: a Django site app with views, templates and static files at /, a designer's static pages imported with the design kept as written, every text, image, menu and contact detail editable in the admin, the karni-site runtime, content read through the default manager, SEO by default (titles, share tags, JSON-LD, sitemap.xml, robots.txt, sized images, karni check --seo), a page test with assert_pages, and public forms from karni make form and the karni_form tag."
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

## Start a site project

`karni new` asks what kind of project it is, and `--kind` says it without
the question:

```bash
karni new "Crumb Bakery" --kind site                    # a public website
karni new "Crumb Bakery" --kind site --design ../design # built from a designer's pages
karni new "Field Notes" --kind app                      # an API and a React app
karni new "Bake Club" --kind site+app                   # both
```

| Kind | What `karni new` sets up |
|---|---|
| `site` | the site app `website` at `/` on the [`karni-site` module](#the-karni-site-module), the admin as the place the client edits every text, image, menu and page title, registration off (`KARNI_ACCOUNTS_REGISTRATION = False`, staff create the accounts), the roles `staff` and `editor`, and the staff app in `frontend/` for staff (`--no-staff-app` leaves it out, and staff work in the admin) |
| `app` | the API and the React app in `frontend/` for signed-in users, as `karni new` always made |
| `site+app` | both: the site app and karni-site, and the app with its registration and roles |

Every kind has the same security defaults (the
[Content-Security-Policy and headers](security.md#security-headers), the
public-create throttle, `karni check --deploy`) and the production stack. Run
in a terminal, `karni new` asks for the kind. Run by a script or an agent, it
makes an app, or a site with `--design`. `--site-app` names the site app
something other than `website`.

The kind is recorded in pyproject.toml, next to the release the project was
made for:

```toml
[tool.karni]
baseline = "0.5.0"
kind = "site"
```

`karni context` prints it first (`KIND: site (...)`), and the agent files
(`AGENTS.md` and the others, [Karni for AI agents](agents.md)) open with the
kind and its stack, so an agent never asks which technology to use. A
project made before kinds has none recorded, and Karni infers it:
`karni_site` installed makes a site, `frontend/` a staff app.

`--design <folder>` runs, on the new project, the first steps of the
[site-from-design procedure](design-content.md): `karni design analyze`
writes the draft content map `content/design-map.json` and prints the models
it proposes, then `karni import design --editable --map
content/design-map.json` builds the site app, makes everything the client
sees editable and themes the staff app and the admin from the design's
stylesheets. It prints the rest of the procedure as the next steps, with the
project's own paths: the decisions, the models, the content and the loops.

### An app that gets a site

`karni add site` turns an app into a site+app: it wires karni-site into the
project and sets `kind = "site+app"`, then `karni make site website` (or
`karni import design`) makes the site app. `karni make site` and `karni
import design` change the kind the same way when they wire the module. To go
back, set `kind = "app"` again and run `karni rules sync`. The site's files
stay until you delete them: the site app and its include in
`config/urls.py`, and karni-site in pyproject.toml and config/settings.py.

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
  templates/website/base.html the layout: {% karni_seo %} (title, description, share tags), header, footer
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
processor), and includes its URLs (robots.txt and sitemap.xml) before the
site's own. Install it afterwards and run `karni migrate`. The generated
`base.html` shows the site's name from `site`, which the client changes in
the admin, and its `<head>` is [`{% karni_seo %}`](#seo-by-default). A new app first gets the `karni make app` skeleton and its
`# karni:apps` entry. An existing local app gets only the missing site
files, and its `views.py` and `urls.py` are extended in place.

`karni make view <name>` adds a function view, a template that extends
`base.html`, the URL at the marker in the site's `urls.py`, and the same URL
in the page test (see [The page test](#the-page-test)). Its path defaults to
`/<name>/`. A capture such as `<slug:slug>` becomes a view parameter and a
template variable. A view with a capture usually replaces the pages of one
folder (a model's detail pages becoming one view): an `{% ifactive %}` that
named those pages' views gets the folder's path instead (`"/services/*"`),
so the menu item stays marked on every page of the folder. Both commands take `--dry-run`, and `--no-route` when you
want to wire the URL yourself.

A designer's static pages go in with [`karni import design`](#import-a-design),
never by hand. For a site written from scratch, put the client's files under
`static/website/` unchanged and link them from `base.html` with
`{% static %}`. Split the header and footer into
`templates/website/partials/` once they grow. Text and images the client may
change are [blocks](#everything-the-client-edits), menus are
`{% get_menu %}`, and the site's details are `site`: no project writes a
template tag, a filter or a model for them. The client's other content goes
in models and comes from the design with [`karni design analyze` and
`karni design extract`](design-content.md), then [`karni load`](content-loading.md):
never a hand-written loading command.

## Import a design

A designer delivers a folder of static pages: `index.html`, `about.html`,
`services/web.html`, with `css/`, `js/` and image folders next to them.
`karni import design` turns that folder into the site app, with the design
kept as written:

```bash
karni make site website                       # optional: import design runs it when needed
karni design analyze ../design --map content/design-map.json   # the content that repeats
karni import design ../design --app website --editable --map content/design-map.json
karni migrate
karni test
```

With `--editable`, every text, image, menu and contact detail becomes
editable in the admin, with the design's own as the defaults (see
[Everything the client edits](#everything-the-client-edits)). Without it the
pages are plain templates.

With `--map`, the content map `karni design analyze` wrote, the content that
becomes rows has no blocks: the items of each list the map holds (the cards,
the list of courses) and the values of a model's detail pages (a title, an
image, a gallery). The templates render those from the rows once they loop
over them ([Load, then loop](design-content.md#load-then-loop)), and the
client edits the rows in the admin. A block over the same text would be a
copy that the page never shows. The rest of each page (its headings, its
own text) stays a block, and the copy a model's detail pages share has one
key on all of them, which starts with the model's name (`course.`), so the
one template that replaces them keeps it. The record remembers the
map. Delete a source from the map and import again, and its markup is
editable again.

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
  `{% block head %}`, and its body into `{% block content %}`. Every page
  joins `PAGES` in the page test.
- **Puts `{% karni_seo %}` where the design's head tags were.** In
  `base.html` it takes the place of the design's first title, description,
  canonical link or share tag, with the title and description blocks inside
  as the defaults, and any share tag every page has (an `og:image`, a
  `twitter:card`). The tags it writes from each page's title, description
  and address (`og:title`, `og:url` and the like) are dropped, and a share
  tag only one page has goes into that page's `{% block seo %}`. Every other
  head tag stays where it was. See [SEO by default](#seo-by-default).
- **Sizes the design's images.** An `<img>` of the design without `width`
  and `height` gets them from its file, so the page does not jump while it
  loads. A JPEG, PNG or WebP wider than 320 pixels, without a `srcset` of
  its own, gets smaller WebP copies next to it under `static/<app>/`
  (`hero.jpg.640w.webp`) and a `srcset` and `sizes`. A lazily loaded image
  gets `sizes="auto, ..."`, so the browser loads the copy that fits the
  layout: a card's picture at the card's size. The copies need Pillow where
  `karni` runs (`pip install pillow`). Without it the import writes the
  sizes only and says how many images could have copies. The images keep
  their shape whatever the design's CSS sets: `{% karni_seo %}` gives them
  `height: auto`. A `404.html` or `500.html` in the design becomes
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
and passes the same page test. The content that repeats in the pages (cards,
detail pages, galleries) becomes models and rows with
[`karni design analyze`, `karni design extract` and `karni load`](design-content.md),
and the templates loop over the rows. The import is a starting point that
runs again, not a build step: edit the templates freely, and the next import
keeps your edits.

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
  highlight (a backslash before the marker keeps it as typed). A template's
  default reads the markers too: `{% editable "home.title" %}Bread ==worth==
  the walk{% endeditable %}` shows the highlight before anyone edits it. Model fields
  rendered with `{{ value|highlight }}` read the same markers. Bold, emphasis and links are kept, and everything else is
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
  links. `{% site_defaults %}` gives the logo, the favicon and the share
  image as static paths (`share_image="website/img/share.jpg"`), used until
  the client uploads their own.
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
- the business's address becomes `site.address`, seeded with the design's
  text: an `<address>` of text and line breaks, or a block that reads like a
  postal address (a number, two to six parts parted by commas or line
  breaks) beside the phone, email or map link or shown on another page too.
  A block with line breaks renders `{{ site.address|linebreaksbr }}`, one
  with commas `{{ site.address_lines|join:", " }}`, so each place keeps its
  look and the client enters the address once. Places that show different
  addresses stay text blocks, and the report says so.
- opening hours a table, a definition list, a list or lines of text show
  (days, then times or a word for closed, in English, German, French,
  Spanish, Italian, Dutch or Portuguese) become a loop over `site.hours` in
  the design's own markup, seeded once with `{% site_defaults hours="..." %}`.
  When the footer and the contact page both show them, both loop over the
  same rows, seeded from the one whose markup parts days from times, so the
  client enters them once. Lists that show different hours, or a row that
  does not read as hours, stay text blocks, and the report says so.
- an `og:image` every page has becomes the site's default share image
  (`share_image` in `{% site_defaults %}`, with the logo and the favicon),
  so the client replaces it in *Site settings*. Without one, the one image
  no page uses that is named for sharing (`share.jpg`, `og-image.png`) is
  taken, and the report says so.
- a navigation whose items share one markup (a list of links, nested lists
  for a submenu, or links side by side) becomes `{% get_menu %}` and a
  loop, seeded from `templates/<app>/menus/<name>.html`. One whose items
  differ keeps its markup and its link texts become blocks, and the report
  says where. With `--map`, a list whose links are exactly one model's
  detail pages, each once and by its title (a footer's list of every
  treatment, or a submenu), is seeded as that model's rows, so a treatment
  the client adds appears in it by itself. The report names each one.
- headings that highlight words with the same element and class
  (`<span class="highlight">`), or the same element without one (`<em>`),
  set `KARNI_SITE_HIGHLIGHT` in config/settings.py once, so the client
  types `==words==` for the same. Characters a design writes around words
  (`*whole*`) are its text, not a highlight. A `==` in the design's own text
  is written `\==`, so the page shows it as written.

`.karni/design.json` records each block's key and where it was. The next
import gives the same place the same key, so the client's edits stay
attached when the designer changes the text, and the record keeps the
import editable until `--no-editable`. Left as written: `<pre>` (its
whitespace is its meaning), text in attributes (a form field's
placeholder, an `aria-label`), images in stylesheets, and the `<title>` and
description, which are the page's [SEO entry](#seo-by-default).

The client needs the admin and a role. The module declares `editor`:
staff status and the role let a person change the site's content, menus,
details and page titles, and nothing else (no enquiries, users, settings
or redirects). The [module's README](https://github.com/cbsshekhawat18-lab/karni/tree/main/modules/karni-site)
has the settings and every escape hatch.

## The karni-site module

A site app loads its runtime from the `karni-site` module
([modules](modules.md)), never from project code. `{% load static
karni_site %}` at the top of a template gives it every tag and filter below.
`karni explain <tag>` prints one of them (`karni explain image`), from the
same source as this table.

<!-- generated:site-tags -->
| Tag | Write | What it does |
| --- | --- | --- |
| `{% karni_seo %}` | `{% karni_seo %}<title>...</title><meta name="description" content="...">{% endkarni_seo %}` | In base.html's &lt;head&gt;, around the design's own title and description. It writes the page's title, description, canonical link, robots for a hidden page, the Open Graph and Twitter tags and the site's JSON-LD. Each value is the first of: the admin's entry for the page (Page titles and descriptions), `seo` in the view's context (a dict), the page's row, the tags written inside, the site's settings. The page's row is `seo` or `object` in the context when it is a row, else the row in the context whose get_absolute_url() is the page's path. Its fields are the ones `class Karni: seo` names, else seo_title, seo_description and seo_image, else a title, description or image field by a usual name. A detail page that has its row in the context needs no title of its own. |
| `{% image %}` | `{% image obj.photo alt=obj.title width=800 %}` | An &lt;img&gt; of an uploaded image: src, srcset and sizes from its WebP copies, width and height in its proportions, lazy loading. alt is required (alt="" for an image that only decorates). eager=True, or eager=forloop.first in a loop, for the image at the top of a page. sizes="..." replaces the one worked out from width. Any other name=value becomes an attribute, an underscore a hyphen (data_index=1 is data-index="1"). An empty field renders nothing, and the original is shown until its copies exist. |
| `{% editable %}` | `{% editable "home.intro" %}<default HTML>{% endeditable %}` | Text the client edits in the admin. The content is the default: the first render stores it under the key, and the block follows the template until someone edits it. An edited block shows the edited HTML, cleaned to the inline markup KARNI_SITE_INLINE_TAGS allows. The key's first part is the page the admin groups it under. |
| `{% editable_image %}` | `{% editable_image "home.hero" %}<img src="..." alt="...">{% endeditable_image %}` | An image the client replaces. The design's markup stays: an upload changes the &lt;img&gt;'s src (its srcset and &lt;source&gt; elements go), an edited alternative text its alt. With url after the key, it holds a bare address instead, for a style="background-image: url(...)". |
| `{% site_image %}` | `{% site_image "logo" %}<img src="..." alt="...">{% endsite_image %}` | An image from a file field of the site's settings (logo, favicon, share_image): the design's image until one is uploaded in the admin. |
| `{% site_defaults %}` | `{% site_defaults name="Crumb & Co" phone="01234 567890" %}` | The design's values for the site's details (`site` in every template), stored the first time and followed until someone changes them in the admin. It renders nothing. Put it at the top of the layout, before anything reads `site`. |
| `{% get_menu %}` | `{% get_menu "header" seed="website/menus/header.html" as items %}` | A menu's items for a {% for %} loop in the design's markup: item.title, item.url, item.new_tab, item.current (this page), item.active (this page or one under it) and item.children. With seed, a menu the database does not have yet is created from the links in that template. An item with children from a model lists that model's rows, so a new row appears in the menu by itself, and with no title or address of its own it lists them in its place. karni import design --editable --map seeds a list of a model's detail pages that way. |
| `{% ifactive %}` | `{% ifactive "website:about" %} class="active"{% else %}...{% endifactive %}` | Renders its content when one of its patterns names the current page, else the {% else %} part. A pattern is a URL name, wildcards allowed ("website:service_*"), or a path ("/about/", "/blog/*"). Put it where the design marks the current page: a class, a token inside a class, or a whole attribute. It needs the request in the context. karni check reports a name no URL has (SITE002). |
| `{% karni_form %}` | `{% karni_form "contact" button="Send" classes="bootstrap" %}` | A public form that works with and without JavaScript: the fields a visitor fills (the writable fields of the form viewset's create serializer) with labels, limits and errors, the CSRF token and the honeypot. It posts through the viewset's own create, so the access declaration, rate limit and validation are the API's. Options such as fields, rows, labels, widgets, classes, button and editable fit it to the design. Also {% load karni_forms %}. |
| `{% csp_hash %}` | `<script>{% csp_hash %}...{% endcsp_hash %}</script>` | Renders its content unchanged and adds its SHA-256 hash to the script-src of this response's Content-Security-Policy, so the design's inline script runs under Karni's policy. {% csp_hash attribute %} is for an event handler attribute (onclick="..."). |
| `{% csp_allow %}` | `{% csp_allow "style-src https://fonts.googleapis.com" "font-src https://fonts.gstatic.com" %}` | Adds sources to this response's Content-Security-Policy, one directive per argument, next to the markup that loads from that origin. It renders nothing. KARNI_CSP adds them site-wide instead. |
| `|highlight` | `{{ value|highlight }}` | The words a field keeps between the highlight markers (==marked words==), in KARNI_SITE_HIGHLIGHT's tag and class, everything else escaped. \|highlight:"em" names another markup for one value, \|highlight:"" drops the marks, and a backslash before a marker (\==) keeps it as typed. |
<!-- /generated:site-tags -->

The module also gives a site:

- `site` in every template: the site's details from the admin
  ([everything the client edits](#everything-the-client-edits)).
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
can never shadow them. Projects created before Karni 0.5.0 have no marker:
`karni upgrade` adds it ([migration note](migrations/0.5.md)), or add the
include by hand before `*welcome_urls()`.

The scaffold's Caddyfile serves `/static/` and `/media/` from disk and sends
every other path to Django, so the site at `/` works in production with no
change. `collectstatic` copies `static/website/` into `STATIC_ROOT`.

## SEO by default

A site built with `karni make site` or `karni import design` is ready for
search engines without project code:

- **The head.** `base.html` has `{% karni_seo %}` around the design's title
  and description. It writes the page's `<title>`, description, canonical
  link, `noindex` for a hidden page, the Open Graph and Twitter tags and the
  site's JSON-LD (an `Organization`, or a `LocalBusiness` with its address,
  phone, opening hours, logo and social profiles, from the site's
  settings). Each value is the first of: the admin's *Page titles and
  descriptions* for the page, `seo` in the view's context, the row the page
  is about, the template's own tags, the site's settings.

  ```django
  {% karni_seo %}<title>{% block title %}{{ site.name }}{% endblock %}</title>
  <meta name="description" content="{% block description %}{% endblock %}">{% block seo %}{% endblock %}{% endkarni_seo %}
  ```

- **Built with Karni.** The head also carries
  `<meta name="generator" content="Karni">`, so tools that list a site's
  technologies (BuiltWith, Wappalyzer and the like) can tell what it runs
  on. The staff app's `frontend/index.html` carries the same line. It names
  no version on purpose, because a version tells an attacker which known
  flaws to try. `KARNI_GENERATOR` changes the text, and `""` turns it off and
  keeps a design's own generator tag (delete the line from `index.html` too).

- **Detail pages.** A row in the context whose `get_absolute_url()` is the
  page's path gives the page its title ("Wedding cake | Crumb & Co"), its
  description and its share image. `class Karni: seo` names the fields when
  their names are not the usual ones:

  ```python
  class Project(BaseModel):
      class Karni:
          seo = {"title": "name", "description": "intro", "image": "photo"}
  ```

- **sitemap.xml** lists the site's pages and every model's rows that have a
  page, honouring scopes, soft deletes and a published flag (`class Karni:
  sitemap = {"filter": {...}}` to choose).
- **robots.txt** closes the site outside production (`DJANGO_ENV` other
  than `prod`) and names the sitemap in production.
  `KARNI_SITE_ALLOW_INDEXING` decides otherwise.
- **Images.** `{% image project.photo width=400 alt=project.title %}`
  writes `srcset`, `sizes`, `width`, `height` and lazy loading from WebP
  copies made in the background when the image is uploaded (Celery,
  through the project's storage, local or S3). Uploads larger than
  `KARNI_SITE_IMAGE_MAX_SIZE` are scaled down. Until the copies exist the
  original is shown. Pillow is the `karni-site[images]` extra, which `karni
  make site` adds. Without it images are shown as uploaded. The picture at
  the top of a page loads first, not lazily: `eager=True`, or in a loop
  `eager=forloop.first` (a hero slider's first slide).
- **404 and 500 pages.** `templates/404.html` and `500.html` extend the
  site's layout, `karni_site`'s handlers render them with the request while
  `DEBUG` is off, and they are never indexed. With `DEBUG` on you see
  Django's debug page.
- **Set the address in production.** `KARNI_SITE_URL =
  "https://www.example.com"` puts canonical links, share tags and the
  sitemap on the real domain whatever host a request came to.

`karni check --seo` renders every page through Django's test client and
reports titles and descriptions missing or shared between pages, images
without alt text, without width and height or much larger than shown,
broken internal links, and pages missing from the sitemap (`SITE010` to
`SITE018`). It makes the smaller copies of the uploads the pages show that
have none yet, in its own process, and names them, so it passes in
development without a Celery worker. The site keeps queueing them. The [karni-site README](https://github.com/cbsshekhawat18-lab/karni/tree/main/modules/karni-site)
lists every setting.

## Public forms

A contact form, a booking request, a newsletter sign-up and a job application
are the same thing: rows of a model that anyone may create and only staff
read. One command writes the project's side of any of them, and one tag puts
the form in a page:

```bash
karni make form contact name:str email:email subject:str message:text \
    --notify ENQUIRY_RECIPIENTS --app website
karni make form newsletter email:email --app website
karni make form booking_request name:str email:email day:date "service:choice:cut|colour" \
    "phone:phone?" --states "requested>confirmed|requested>declined" --app website
karni make migration --app website && karni test
```

```django
{% load karni_site %}
{% karni_form "contact" %}
```

`karni make form <name> <field:type> ...` takes the fields a visitor fills,
in `karni make model`'s field DSL, and writes:

| File | What |
|---|---|
| `<app>/models.py` | the model: the visitor's fields, a `status` [StateField](models.md) for the inbox (`--states`, by default new moves to replied or archived, and replied to archived), staff-only `notes`, `class Karni` (`field_roles` hides both from visitors, `audit`, `dashboard`), `class AdminMeta` (the admin inbox: newest first, filtered by status, searchable) and a `SearchField` for the search |
| `<app>/viewsets.py` | a `BaseViewSet` with `Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())` (`--role` names another role) |
| `<app>/listeners.py` | with `--notify SETTING`: a queued listener that emails each new row to the addresses in that setting |
| `<app>/templates/<app>/email/<name>_subject.txt`, `_body.txt` | with `--notify`: the email, yours to edit |
| `config/settings.py`, `.env.example`, `.env.prod.example` | with `--notify`: `SETTING = env.list("SETTING", default=[])` and the line to fill in each env file |
| `<app>/tests/test_<name>_form.py` | anonymous submit, the form without JavaScript, the email (or none), the staff-only fields, the rate limit, staff-only reading, and `assert_crud` for the role |
| `frontend/src/pages/` | the staff app's list, detail (with the lifecycle buttons) and form pages |
| `config/urls.py` | `path("", include("karni_site.urls"))`: the view every form posts to |

A form without `--notify` sends nothing. No throttle is written: Karni limits
each visitor's creates on a public `create` (`KARNI_PUBLIC_CREATE_RATE`,
default 10 an hour) and gives it a honeypot field
([security](security.md#what-karni-does-by-default)).

### The tag

`{% karni_form "contact" %}` renders the fields a visitor fills (the writable
fields of the viewset's create serializer, as an anonymous visitor sees them)
with their labels, required marks, limits, choices and help text, the CSRF
token and the honeypot field. It works without JavaScript:

- The browser posts to karni-site's view, which saves through the viewset's
  own `create`. The access declaration, the rate limit, the honeypot,
  validation and change history are the API's.
- A sent form redirects back to the page with `?sent=contact`, where the tag
  shows the success message. A filled honeypot looks sent and saves nothing.
- A refused form renders the page again, by its own view, with the values
  kept and the error under each field: `400` when a value is wrong, `429`
  with the rate-limit message, `403` when the visitor may not send it.

With JavaScript, `karni_site/forms.js` (loaded once per page) posts the same
data in place and shows the same messages and inline errors. It is a static
file with no inline code, so the enforced Content-Security-Policy lets it
run as it is.

A design's own CSS applies through the tag's arguments, the settings and the
templates:

```django
{% karni_form "contact" classes="bootstrap" button="Send message" %}
{% karni_form "booking_request" rows="name,email" labels="day: Preferred day"
   placeholders="name: Jane Doe" widgets="service: radios" field_class="field"
   row_class="form-row" required_class="req" button_class="btn btn-accent" %}
```

`classes="bootstrap"` uses Bootstrap 5's form classes.
`KARNI_SITE_FORM_CLASSES` sets the classes of every form,
`KARNI_SITE_FORM_PRESETS` adds named sets, and
`templates/karni_site/forms/form.html` or `field.html` in the project (or
`karni_site/forms/<form>/<field>.html` for one field) replaces the markup.
The [karni-site README](https://github.com/cbsshekhawat18-lab/karni/blob/main/modules/karni-site/README.md)
lists every argument and setting.

`editable="<key>"` makes the form's texts editable in the admin like the
rest of the page: each field's label and placeholder, the button and the
sent message become blocks under that key (`home.booking.email.label`,
`home.booking.button`), with the tag's own texts as their defaults:

```django
{% karni_form "booking_request" labels="day: Preferred day" button="Book now" editable="home.booking" %}
```

When the site came from `karni import design`, the import lists each
`<form>` of the design (it is in `.karni/design.json` too), and `karni make
form` names the template and the line of the form it replaces, with the tag
that keeps that form's class names, rows, labels, placeholders, button and
the attributes of its controls (a textarea's `rows`, an input's `min`, `max`,
`step` or `pattern`, as `attrs="message: rows=4"`). `karni make form <name>
--tag` prints that tag again later and writes nothing, so a form made
already does not have to be made again to see it.
It matches each of the design's controls to a field of the form: by its
name, then by its label and its type (the design's `day` with the label
*Preferred date* fills `preferred_date`), then by its type alone when one
control and one field of that type are left. It says which control fills
which field, and names the controls no field fills and the fields the
design does not show. After an editable import the tag gets `editable=`,
and its arguments are always plain text:

```text
design: website/templates/website/home.html:8: <form action="book.php"> with name, email, day, service (the fields of booking_request)
fields: the design's form fills name -> name, email -> email, day -> day, service -> service.
replace: in website/templates/website/home.html, replace that <form> ... </form> (line 8) with:
    {% karni_form "booking_request" form_class="booking-form" message_class="form-note" row_class="form-row" field_class="field" required_class="req" button_class="btn btn-accent" rows="name,email" labels="day: Preferred day" placeholders="name: Jane Doe" button="Book now" editable="home.booking_request" %}
```

### The email

```python
@on_created(Contact, queued=True)
def notify_contact(contact: Contact) -> None:
    """Emails each new contact to settings.ENQUIRY_RECIPIENTS (after commit)."""
    notify_recipients(
        contact,
        setting="ENQUIRY_RECIPIENTS",
        template="website/email/contact",
        reply_to=contact.email,
    )
```

The listener runs in a Celery worker once the row is committed
([queued listeners](events.md#queued-listeners-shouldqueue)), so the
visitor never waits for the mail server. `notify_recipients` from
`karni_site.notify` renders the two templates, sets `Reply-To` to the
visitor's address so staff answer by replying, and sends to every address in
`ENQUIRY_RECIPIENTS` (a list in settings, comma-separated in `.env`). An
empty setting sends nothing and logs a warning. The body lists the visitor's
fields, leaving out an optional one they left empty, and links the row's
admin page with a full address (`{{ admin_url }}`): on `KARNI_SITE_URL` when
it is set, else on the host the visitor's request came to, which the queued
task carries.

### The API stays the same

The form is an ordinary resource: `/api/contacts/` takes the same create, as
JSON or multipart, for a mobile app or another site. A `201` means the row
was created, a `400` carries `{"field": ["message"]}`, a `429` means the
visitor sent too many. The staff app's pages and the admin read and answer
the submissions.

## Check it

`karni routes` lists the site's views with their names (`website:home`), and
`karni context` prints them on its `SITE:` line. `karni check` covers the
site app like any other app, runs `karni-site`'s checks (`SITE001`: the
templates get the request, `SITE002`: every `{% ifactive %}` names a URL
that exists, `SITE004`: the templates get `site`, `SITE005`: the redirect
middleware is installed, `SITE008`: no block key has two defaults, `SITE020`:
every `{% karni_form %}` names a form that exists), and `karni test` runs its
page test and each form's test. `karni check --seo` renders every page
and checks what search engines read ([SEO by default](#seo-by-default)), and
names a menu item whose page is gone (`SITE007`).

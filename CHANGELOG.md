# Changelog

Every package in this repository (`karni`, `karni-cli`, `karni-payments`,
`@karni/ui`, `@karni/payments-ui`) is released at one version, in lockstep.
See [docs/releasing.md](docs/releasing.md).

Breaking changes and deprecations are recorded in machine-readable form in
`packages/karni/karni/changelog/<version>.toml` and explained in
`docs/migrations/<version>.md`. The TOML file is what `karni upgrade` reads to
apply codemods and list the manual steps. This file is the human summary.

## Unreleased

- **The admin is light only by default.** `KARNI_ADMIN_THEME` (default
  `"light"`) pins unfold's light palette and hides its light / dark / system
  switch, read on every request. `"auto"` brings the switch back and
  `"dark"` pins the dark palette. See
  [docs/admin.md](docs/admin.md#theming) and the
  [migration note](docs/migrations/0.4.1.md#the-admin-is-light-only).
- **Everything a client sees on a public site is edited in the admin.**
  The karni-site module now holds the site's own details (`SiteSettings`:
  name, tagline, logo, favicon, the default share image, address, phone,
  email, map link, opening hours and social links, as `site` in every
  template, swappable through `KARNI_SITE_SETTINGS_MODEL`), editable blocks
  (`{% editable "home.intro" %}...{% endeditable %}` and `{% editable_image
  %}`, where the template's content is the default, stored on the first
  render and followed until someone changes it, edited as plain text with
  history, cleaned to a safe inline subset by a standard-library sanitiser
  behind `KARNI_SITE_SANITIZER`, with a highlight convention set by
  `KARNI_SITE_HIGHLIGHT`, and one cache read per page), menus (`{% get_menu
  "header" as items %}` looped in the design's own markup, nested items that
  go to a page by URL name, a row's page or an address, children from a
  model's rows, the current page on each item, seeded from the design's
  navigation), redirects (301 or 302, answered by
  `karni_site.middleware.RedirectMiddleware` where the site has no page,
  query strings passed on, loops refused with SITE006), per-page titles and
  descriptions (`PageSeo`, looked up with `karni_site.seo.page_seo(request)`)
  and an `editor` role that changes the content and nothing else. `karni
  import design --editable` marks every text, image, menu and contact detail
  of a designer's pages with these tags, with readable keys that
  `.karni/design.json` keeps stable across imports. `karni make site` and
  `karni add site` wire the middleware and the `site` context processor,
  and `karni check` reports either missing (SITE004, SITE005).
  [docs/public-site.md](docs/public-site.md#everything-the-client-edits).
- **A module can declare roles: the `karni.roles` entry point.** Its roles
  join `KARNI_ROLES` (the project's own win for the same slug), so `karni
  sync-roles`, the permission matrix and `karni context` treat them like the
  project's. [docs/modules.md](docs/modules.md#7c-optional-karniroles-roles-a-module-declares).

- **A designer's static pages become the site: `karni import design <dir>
  --app <app>`.** The folder's HTML, CSS, JavaScript and images become a site
  app with the design kept as written. The files are copied unchanged under
  `static/<app>/`, the header, navigation and footer every page shares go
  into `base.html` (a block some pages share becomes a partial, a page whose
  header differs keeps its own in a block override), each page becomes a
  template extending it with a view and a route (`index.html` answers `/`,
  `about.html` `/about/`, a folder a nested route), links become `{% url %}`
  and asset paths `{% static %}` (anchors and query strings kept, `srcset`
  and `url(...)` in style attributes included), a meta-refresh stub becomes a
  permanent redirect, and the current menu item is marked with
  `{% ifactive %}` wherever the designer marked it, whatever class or
  attribute the design uses. Inline scripts are wrapped in `{% csp_hash %}`
  so they run under the Content-Security-Policy, and the origins a page
  loads from are declared with `{% csp_allow %}`. Every page joins the page
  test. The report names the files no page or stylesheet uses and anything
  that could not be mapped. `.karni/design.json` records the import: a
  second run with a new version of the design reports what changed
  (`--diff` reports only) and keeps every file the project edited since
  (`--force` replaces them). The parsing, comparison and rewriting live in
  `karni_cli.design` for the later `karni design` commands.
  [docs/public-site.md](docs/public-site.md#import-a-design).
- **The content that repeats in a design becomes models and rows: `karni
  design analyze` and `karni design extract`.** `analyze <dir>` reads a
  designer's pages and finds the structures repeated within and across them
  (cards, list items, a gallery inside each project, a page per doctor). It
  infers the fields from the markup (a heading with its highlighted words,
  text, an image and its alt, a link, a list of tags, a date, a price, a
  number), merges the places that show the same items (a card that links to
  a detail page, an anchor that is an item's `id`, a shared key or title),
  finds the relations (a list of links to another model's items, an
  attribute holding its keys, items nested in another model's items) and
  prints ready-to-run `karni make model` commands, models others point at
  first. Names come from the design's classes, headings, labels, pages and
  folders. What the markup cannot settle (a list on a detail page that may
  be hand-picked or derived, a few items shown on the home page, a card
  styled on its own that holds a list item's values) is a decision for the
  agent, with the evidence. The report also gives the `KARNI_SITE_HIGHLIGHT`
  that renders the design's highlighted words, or says that `karni import
  design --editable` already wrote it. `--json` prints it all as stable
  JSON, and `--map <file>` writes a draft content map. `extract <dir> --map
  <file>` reads the pages with the map and writes their content in the
  `karni load` format: values parsed by type, highlighted words between the
  site's marker (`==words==`, the map's `"marker"`), relations by key,
  children nested, image paths relative to the output file. It refuses
  while a decision is open (C122) or the map cannot be followed (C121).
  [docs/design-content.md](docs/design-content.md).
- **`karni load --dry-run` shows a diff per model.** Each row it would create,
  each row it would change with the fields that change (old and new value),
  each file it would upload and each child `--prune` would delete, the first
  20 rows of a model listed and the rest counted. `--json` carries the same
  rows under `"changes"`. [docs/content-loading.md](docs/content-loading.md#validation-and-errors).
- **`karni make model --order <field> --key <field>`** writes `Meta.ordering`
  and `Karni.import_key`, the field `karni load` matches rows on (a child
  row: its parent plus that field, such as `position`).
- **One convention for highlighted words: `{{ value|highlight }}` in
  karni-site.** A model field keeps highlighted words the way an editable
  block does, between `KARNI_SITE_HIGHLIGHT`'s marker (`==words==`), and the
  filter renders them in the setting's tag and class, everything else
  escaped. `|highlight:"span.dot"` names another markup for one value,
  `|highlight:""` drops the marks. A backslash before the marker (`\==`)
  keeps it as typed, in a field and in an editable block alike.
- **New agent procedure `site-from-design`**: import, analyze, models,
  extract, load, then templates that loop over the rows. Run `karni rules
  sync` for its slash command files.
- **New module `karni-site`: the runtime of a public site.** `{% ifactive
  "<app>:<name>" %}` marks the current page in a menu around whatever markup
  the design uses, `{% csp_hash %}` and `{% csp_allow %}` let a design's
  inline scripts and other origins pass the Content-Security-Policy for that
  response only, and `karni_site.views.page_not_found` and `server_error`
  render the site's own 404 and 500 pages with the request and fall back to
  a plain page when one fails. `karni check` runs SITE001 (templates get the
  request) and SITE002 (every URL name an `{% ifactive %}` names exists).
  `karni make site` wires the module the way `karni add site` does, sets
  `handler404` and `handler500`, and writes `templates/500.html`. In
  core, `karni.security.extend_request_csp(request, {...})` adds sources for
  one response from code that runs while it is built, and a hash added next
  to `'unsafe-inline'` is left out, because a browser would otherwise ignore
  the `'unsafe-inline'`. [docs/modules.md](docs/modules.md).
- **Public forms in one command: `karni make form`.** `karni make form
  contact name:str email:email subject:str message:text --notify
  ENQUIRY_RECIPIENTS` writes a contact form, a booking request, a newsletter
  sign-up or a job application alike: the model (the visitor's fields from
  the field DSL, a `status` StateField for the inbox from `--states`,
  staff-only `notes`, both hidden from visitors through `field_roles`,
  `audit`, `dashboard`, an admin inbox and an indexed search), a
  `BaseViewSet` with `create=Public()` read by `--role` (Karni's rate limit
  and honeypot apply, no throttle is written), the project's tests
  (anonymous submit, without JavaScript, the email, the protected fields,
  the rate limit, staff-only reading, `assert_crud`), the staff app's pages,
  and with `--notify` a queued listener, its email templates and the
  recipients setting. Without `--notify` nothing is sent. When the site came
  from `karni import design`, the command names the template and line of
  the design's `<form>` it replaces and prints the tag with the arguments
  that keep that form's class names, rows, labels and button. The import
  now records each page's forms in `.karni/design.json` and lists them in
  its report. [docs/public-site.md](docs/public-site.md#public-forms).
- **karni-site: `{% karni_form "<name>" %}` and its view.** The tag renders
  the fields a visitor fills from the form viewset's create serializer, with
  labels, required marks, limits, choices, the CSRF token and the honeypot.
  It works without JavaScript: the browser posts to `karni_site:form`, which
  saves through the viewset's own `create` (access, rate limit, honeypot,
  validation and history are the API's), then redirects back with
  `?sent=<name>` or renders the page again, by its own view, with the
  errors next to each field (400, 429, 403). `karni_site/forms.js` submits
  in place with inline errors and the rate-limit message, and runs under
  the enforced Content-Security-Policy because it is a static file with no
  inline code. Class names and markup come from the tag's arguments
  (`classes="bootstrap"`, `field_class`, `rows`, `labels`, ...), the
  `KARNI_SITE_FORM_*` settings and overridable templates.
  `karni_site.notify.notify_recipients` emails a row to the addresses a
  setting names, from the project's templates, with `Reply-To`. New codes:
  SITE020 (a check: a tag names a form that does not exist), SITE021 to
  SITE023. Rule K309 and the `new-model` procedure name `karni make form`.
- **A new project's staff app is ready to hand over.** The scaffold's
  `layout.tsx` wraps every page but a sign-in page in `<AuthGuard explain>`,
  so a visitor who is not signed in gets the sign-in prompt in place of a
  page of errors, and offers "Sign out". Its menu comes from the new
  `routeNavItems` in `@karni/ui` (one entry per static route, detail and
  "new" routes left out, the sign-in page listed only while nobody is signed
  in), which the example apps use too. Its home page is the new
  `<Dashboard>`: a `Stat` tile per count and the newest rows of every model
  that declares `class Karni: dashboard = {...}` (counts of every row, the
  new ones, one per state, and named counts by list filters), published as
  `x-karni-dashboard` on the list operation and checked at boot (`E133`).
  Nothing in the page names a model. See
  [docs/api.md](docs/api.md#the-staff-dashboard).
- **`ResourceDetail` renders a `StateField`'s transitions as buttons.** One
  per state the record may move to from its current state
  (`x-karni-transitions`), shown when the API lets this user write the field.
  A click PATCHes the field, a move into a terminal state asks first, and a
  refusal shows the server's own sentence. `transitions` tunes labels,
  confirmations and who may, or hides them, and the `Transitions` slot
  replaces them. `ResourceTable` puts a lifecycle field first in its derived filters.
  The parser exposes `transitions` and `initial` on a `FieldDef`.
- **`karni ui detect --css <path>` maps any stylesheet.** Plain CSS, a
  Bootstrap-style sheet, a design with no variables at all (then the body,
  link, button, heading and input rules are read), one file or a directory
  of pages. Custom properties whose name means a role are "found", values
  taken from rules or derived (ring, input, a contrasting primary
  foreground) are "inferred", the rest are "defaulted", and the report says
  which. A dark-only design is written for both modes. It is also a function,
  `karni_cli.uitheme.detect_css(paths)`, which `karni import design` calls.
  See [docs/theming.md](docs/theming.md#any-stylesheet-css).
- **One theme for the staff app and the admin.** `KARNI_THEME_CSS` (default
  `frontend/src/karni-theme.css`, the file `karni ui detect` writes) is
  served to the admin as the static file `karni/project-theme.css` by the
  new `karni.admin.theme.ProjectThemeFinder` (live under `runserver`,
  copied by `collectstatic`, same origin so the Content-Security-Policy
  allows it) and loaded third in `UNFOLD["STYLES"]`. Without the file the
  URL serves an empty stylesheet. See
  [docs/theming.md](docs/theming.md#one-theme-for-the-staff-app-and-the-admin).
- **`karni-theme.css` keeps dark mode.** Light-only colours are now written
  under `:root:not(.dark)`, so they no longer override Karni's dark palette
  under `<html class="dark">`. A file written by an earlier release is
  regenerated with `karni ui detect --force`.
- **Public server-rendered pages have a home.** `karni make site <app>`
  creates a site app (function views, `urls.py` with `app_name`, templates,
  static files, a 404 page) and includes it at `""` in `config/urls.py`, so
  its home page replaces the welcome page. `karni make view <name> --app
  <app>` adds a page. New rule K309 says where a public site goes, and K302
  and K306 now say they are about app screens. `karni context` lists the
  site's routes on a `SITE:` line. [docs/public-site.md](docs/public-site.md)
  covers reading content, SEO basics and public forms.
- **`assert_pages` tests a public site's pages.** `assert_pages(client,
  urls)` in `karni.testing` (and `self.assert_pages(urls)` on
  `APITestCase`) requests each page and checks a 200, a non-empty `<title>`
  and `<meta name="description">`, an `alt` attribute on every `<img>`
  (`alt=""` passes), that every same-site link, stylesheet and image answers,
  and that a URL the site does not have answers 404. Every problem is
  reported in one `E618` error, one line per page and problem, and each URL
  is requested once per call. Other hosts are not requested. The test client
  serves no static files, so a `{% static %}` URL is looked up with the
  staticfiles finders. `karni make site` writes `<app>/tests/test_pages.py`,
  which calls it on a `PAGES` list, and `karni make view` adds each new URL
  at its `# karni:pages` marker. The generated `base.html` passes it.
  Escape hatches: `follow=`, `check_links=`, `require_title=`,
  `require_description=`, `require_alt=`, `not_found_url=`, `ignore=`,
  `hosts=`, and a `PageParser` subclass as `parser=`. See
  [docs/testing.md](docs/testing.md#public-pages-assert_pages).
- **`config/urls.py` has a `# karni:urls` marker** where `karni make site`
  inserts its include. `karni upgrade` adds it to existing projects
  ([docs/migrations/0.4.1.md](docs/migrations/0.4.1.md)).
- **Security: `--access public-read` no longer lets every signed-in user
  write.** In 0.4.0 the preset wrote `Access(read=Public(),
  write=Authenticated())`. A new project also has open self-registration, so
  anyone who signed up could create, change and delete every row of the
  resource, and the generated test, acting as any signed-in user, passed. It
  was found in a real project built on 0.4.0. The preset now writes
  `write=HasRole("staff")`, and `--access public-read:<role>` names another
  role. This changes a security-relevant default: review every viewset that
  declares `read=Public(), write=Authenticated()`. `karni upgrade` lists the
  step, and [the 0.4.1 migration note](docs/migrations/0.4.1.md) has the
  details.
- **Public forms are protected by default.** A viewset whose `create` anyone
  may call (`create=Public()`) is limited to `KARNI_PUBLIC_CREATE_RATE` (10
  an hour per caller, by client IP for anonymous callers) with no
  `throttle` declaration. `Throttle(create=...)` replaces the rate and
  `Throttle(create=None)` or `KARNI_PUBLIC_CREATE_RATE = None` turns it off.
  A request that fills the honeypot field `KARNI_PUBLIC_CREATE_HONEYPOT_FIELD`
  (default `homepage`) is answered 202 and saves nothing. The field is named
  in the schema as `x-karni-honeypot`, never as a body field, and
  `@karni/ui`'s `ResourceForm` renders it hidden. The import endpoints of such
  a viewset now need a signed-in user, and an anonymous caller can no longer
  read an import job. `karni make model ... --access public-create` writes a
  public form's declaration, and the `new-model` agent procedure names it.
  The pytest plugin starts each test with empty
  rate-limit counters. This changes a default: see
  [the 0.4.1 migration note](docs/migrations/0.4.1.md#public-creates-are-rate-limited).
- **Security headers on every response.** `karni.security.SecurityHeadersMiddleware`
  sends a Content-Security-Policy (report-only while `DEBUG` is on) and a
  Permissions-Policy. The default policy allows what Karni serves: the admin
  (with `'unsafe-eval'` for its Alpine.js, on admin pages only), the API docs
  pages from their CDN, the welcome page's two scripts by hash and the
  `@karni/ui` app's theme script by hash. `KARNI_CSP` adds sources (Google
  Fonts, analytics) or removes a directive, `None` turns the header off,
  `KARNI_CSP_REPORT_ONLY` overrides the `DEBUG` choice, and `@csp_extend` and
  `@csp_exempt` adjust one view. `KARNI_PERMISSIONS_POLICY` allows a browser
  feature back. A new project's Swagger page uses drf-spectacular's split
  view, which needs no inline script. See
  [security headers](docs/security.md#security-headers).
- **`karni check --deploy`.** It runs Django's `check --deploy` plus ten
  Karni deploy checks, `karni.W510` to `karni.W519`: `DEBUG`, a strong
  `SECRET_KEY`, `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` without wildcards,
  HSTS, secure cookies, the admin off `/admin/`, CORS not open to every
  origin, and an enforced Content-Security-Policy whose `script-src` allows
  no injected script. Each finding prints with its code and fix, a warning
  fails the run, and a Django warning that a Karni check covers is printed
  once. `manage.py check --deploy` runs the same checks. `karni_check` now
  prints the findings of a failing Django check, which it used to swallow.
  `CSRF_TRUSTED_ORIGINS` is read from the environment, and the scaffold's
  `.env.example` lists the production values to set. See
  [deploy checks](docs/security.md#deploy-checks).
- **A production stack in every new project, booted in CI.** `karni new`
  (and `karni make deploy compose` in an existing project) writes
  `docker-compose.prod.yml`, the `Caddyfile` and `.env.prod.example`. The
  stack has a one-shot `release` service (the deploy checks, `migrate`,
  `collectstatic`, then `manage.py karni_publish_web`), `django` (gunicorn with
  uvicorn workers), Celery `worker` and `beat`, `caddy` (automatic TLS for
  `DOMAIN`, static and media files from the shared volume, the staff app at
  `/app/`, everything else proxied to Django), `db`, `redis` and `backup`, with
  health checks, restart policies, memory limits, log rotation, named volumes
  and no bind mount of source. Flags cover what differs between projects:
  `--app-path`, `--app-domain`, `--no-app`, `--no-celery`, `--no-db`,
  `--no-redis`, `--no-backups`, `--domain`. The scaffold's `Dockerfile` gains
  a `staff-app` stage (the frontend built with Vite's base set to the app's
  path) and a `backup` target, and `frontend/src/routes.tsx` passes that base
  to the router. `karni_publish_web` copies the Caddyfile, the built staff app
  and a snippet with the security headers Django sends, computed from the
  project's settings, into the volume Caddy reads, so a release or a rollback
  changes them together. A new CI job, "Production stack (compose, smoke)",
  creates a project, builds both images, starts the stack with generated
  production values and checks health, a public page, the admin login,
  static files, the staff app, the http redirect, the security headers, the
  deploy gate and a restored backup. See [docs/deploy.md](docs/deploy.md).
- **`karni check --deploy` at container start.** The production image's
  entrypoint, `python -m karni.deploy.entrypoint`, runs the deploy checks
  before its command and exits with `E520` when they fail.
  `KARNI_SKIP_DEPLOY_CHECK=1` starts it anyway, logged on every start, and
  `KARNI_DEPLOY_CHECK_COMMAND` replaces the check. `python -m
  karni.deploy.healthcheck` is the container health probe: it asks `/health/`
  with an allowed host and `X-Forwarded-Proto: https`, which a plain request
  in production does not pass.
- **Backups with retention, and a tested restore.** `karni.deploy.backup`
  (`karni-backup` in the backup image) dumps the database with `pg_dump` and
  archives the media every `KARNI_BACKUP_INTERVAL_HOURS`, keeps the newest
  `KARNI_BACKUP_KEEP`, uploads to `KARNI_BACKUP_S3_BUCKET` when it is set, and
  restores in one transaction (`restore`, with `--create` for a second
  database or `--clean` over the live one). `counts --against` compares the
  row counts of two databases. A failure is `E521` and turns the service
  unhealthy. It uses the standard library only.
- **`KARNI_HEALTH_CHECKS` is read from the environment** (comma-separated),
  so a deployment without a Celery worker leaves the Celery check out of
  `/health/ready/`.
- **`karni make test` acts as the role that may write.** For a viewset whose
  writes need a role, the generated test uses the role the `write` predicate
  names (then `create`, then `read`), so it exercises real creates, updates
  and deletes instead of confirming the refusals.
- **New warning `karni.W102`.** While registration is open, `karni check`
  warns for every routed viewset whose `write` is `Authenticated()` or
  `Public()` without a narrowing `HasRole`, `Granted`, `Owned` or `Can`.
  `create=Authenticated()` with an owned `write` is not reported.
- **`KARNI_ACCOUNTS_REGISTRATION` turns self-registration off.** It defaults
  to `True`, so existing projects do not change. `False` leaves `register/`
  out of the URLs (404) and out of the OpenAPI schema.
- **`assert_crud` sends a real image for a required `ImageField`.** The
  create and update bodies carried `<field>.txt` for every file field, and
  DRF's `ImageField` answered 400 ("Upload a valid image"), so every model
  with a required image failed the create and update checks. A required
  image now gets a 1x1 PNG made with Pillow (`E501` names `pip install
  'karni[images]'` when it is missing), a plain `FileField` keeps the text
  upload, every request gets a fresh upload (one passed in `payload=` is
  rewound), and the stored file must not be empty after the create and the
  update. `assert_isolated` posts such a body as multipart too, where it
  raised `UnicodeDecodeError` on the PNG. Two related messages changed. When the declaration refuses every
  write to the role, the report lists `no write exercised` in `skipped` and
  `assert_crud` warns, since such a run proves refusals only (pin them with
  `expect=` when they are the point). When the rows the run created are
  missing from the list, the message names the read rule and `karni
  why-empty`, instead of blaming the paginator.
- **`karni load` loads a project's real content from a file.** A JSON or
  YAML file maps model labels to rows. Each row is matched by its natural
  key (`Karni.import_key`, `Karni.natural_key`, a unique slug, or a unique
  constraint) and created or updated, so a second run with the same file
  changes nothing and says so. Relations name their targets by natural key.
  File and image fields hold paths relative to the content file and upload
  once (`--refresh-files` uploads again). A nested list holds a row's
  children, matched by parent and key or position, and `--prune` deletes the
  ones it no longer lists. The whole file loads in one transaction through
  the API's serializer and `clean()`, and one bad row rolls everything back
  with an error naming the file, model, key and field (`E804`, `E805`).
  `--dry-run` prints created, updated and unchanged per model. `--as USER`
  attributes the writes, and the change history records the load as one
  batch. It reuses the importer's row logic (`karni.transfer.imports`), which
  gains the escape hatches the loader needs. See
  [Loading content](docs/content-loading.md).
- **`karni seed` refuses tables that already hold rows.** It prints the
  models it will write to, then refuses (`E617`) when one of their tables
  already holds rows, because seed cannot tell its own rows from real
  content. The user table is left out and `--model` narrows the check, so a
  fresh project still seeds without flags. `--reset` starts over and
  `--force` adds demo rows on top. See
  [the migration note](docs/migrations/0.5.md#karni-seed-refuses-tables-that-already-hold-rows).
- **The case study page is removed**, with the before/after line counts the
  README quoted from it. The `examples/social-leads` app stays as a practice
  project and keeps running in CI.
- **A new project's frontend requires npm 11, and Karni says so.** npm 10,
  which Node 20 and 22 bundle, crashed in `npm install` of a fresh scaffold
  with `Cannot read properties of null (reading 'edgesOut')` while it
  resolved Vite 8's optional peers. The newest npm 10 (10.9.9) has the same
  bug, and npm 11 fixed it. The scaffold's `frontend/package.json` now
  declares `"engines": {"node": ">=20.19", "npm": ">=11"}` and its
  `frontend/.npmrc` sets `engine-strict=true`. npm runs that check only after
  the step that crashes, so it stops npm 10 with `EBADENGINE` once a
  `package-lock.json` exists, not on the first install. For the first
  install, the quickstart now has a step that works on any supported Node:
  `npx --yes npm@11 install`. `karni doctor` flags an npm below 11 and a Node
  outside Vite 8's range, with the fix. When ESLint or jscpd is missing,
  `karni check` names the npm requirement and what to run on npm 10. CI runs
  the quickstart on Node 20 with its bundled npm as well as on Node 24.
- **A rate limit for one action.** `throttle = Throttle(create="10/hour")` on
  a `BaseViewSet` limits each caller of that action, on top of the
  project-wide `anon` and `user` throttles. A public contact form no longer
  needs a hand-written `get_throttles()`. It is DRF's throttle under the
  scope `"<route>.<action>"`, so `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`
  replaces the rate or switches it off with `None`. The OpenAPI schema
  publishes the rate as `x-karni-throttle`, and a bad declaration is `E132`.
  See [rate limits](docs/api.md#rate-limits).
- **`env` and `SILENCED_SYSTEM_CHECKS` after `karni_settings()`.** The call
  leaves `env`, the django-environ reader Karni uses, in the settings module,
  so a setting added below it reads `.env` without `import os`. It is also
  importable as `from karni.conf import env`. `SILENCED_SYSTEM_CHECKS` now
  starts as an empty list, so `SILENCED_SYSTEM_CHECKS += ["karni.W967"]` no
  longer raises NameError. The `karni.W967` hint shows that exact line.
- **`karni make model` asks the project about Pillow.** The ImageField note
  appears only when the project's interpreter cannot import Pillow, or when
  there is no host interpreter to ask (a Docker-only project). The scaffold
  keeps depending on plain `karni`: `karni[images]` only adds Pillow, a
  native dependency a project without image fields does not need, and the
  note says to list `karni[images]` when one is added.
- **One dev port: `KARNI_DEV_PORT`.** Set it in `.env` and `karni serve
  --local` runs Django on it, the scaffold's `frontend/vite.config.ts`
  proxies `/api` and `/health` to it (read from `../.env` with Vite's
  `loadEnv`), and `docker-compose.yml` publishes Django on it. The default
  stays 8000, and `KARNI_API_PROXY` still wins when set. `karni serve --local`
  prints how to point the frontend at the server whenever the two disagree
  (`--port`, `--host`, a `KARNI_API_PROXY` that names another address, or a
  `vite.config.ts` from before this setting), and a bad `KARNI_DEV_PORT` is
  `C007`. The example apps' configs and compose files follow the scaffold.
- **Settings read during the call fail loudly below it.** `karni_settings()`
  reads `KARNI_AUTH_MODE`, `KARNI_2FA`, `KARNI_SOCIAL_AUTH`,
  `KARNI_SOCIAL_PROVIDERS`, `KARNI_FRONTEND_URL`, `KARNI_AUTH_THROTTLE_RATES`,
  `KARNI_JSON_LOGS`, `KARNI_CACHE` and `KARNI_STORAGE` during the call to
  compute other settings. Assigned below the call, one of them changed
  nothing and said nothing. Now the system check `karni.E508` fails startup
  and names the setting, what was computed from it, and the fix (move it
  above the call or pass it as a keyword). `KARNI_CACHE` and `KARNI_STORAGE`
  defined above the call build `CACHES` and `STORAGES`, as the environment
  does. The list is generated into [docs/settings.md](docs/settings.md) from
  `karni.conf.CALL_TIME_SETTINGS`, and the scaffold's `settings.py` names it.
- **`KARNI_ADMIN_LOGO` works wherever it is assigned, and on the login
  screen.** It was read during the call, so a value assigned below it was
  silently ignored. The admin now reads it on every request through
  `karni.conf.admin_logo.site_logo` and `site_icon` in `UNFOLD`, a bad value
  fails startup validation (`E303`), and the login screen shows the logo
  above its title (`karni_admin/login.html`, set as the admin site's
  `login_template` unless the site has one). Replacing `UNFOLD` below the
  call while a logo is set is `karni.E508`.
- **`karni make model` adds the images extra to pyproject.toml.** With an
  image field, the `karni` requirement in `[project].dependencies` becomes
  `karni[images]`, keeping its version spec, markers and other extras. Only
  that one string changes, `--dry-run` shows the diff, the note names the
  change and the reinstall (`pip install -e .`), and a project that lists the
  extra already is left alone.
- **`karni doctor` finds a local PostgreSQL and Redis.** Two new lines,
  `database` and `redis`, show what `DATABASE_URL` and `REDIS_URL` name
  (from the environment, `.env` or Karni's default, password masked) and
  whether the server answers: a socket connect with a short timeout and one
  protocol exchange, nothing read or written. When `.env` still names the
  compose hosts `db` and `redis` and they do not resolve, doctor looks on
  `127.0.0.1` at the default port and the configured one, and prints the
  exact `.env` lines for the local services (`DATABASE_URL=postgres://<your
  user>@127.0.0.1:5432/<project>`, `createdb <project>`,
  `REDIS_URL=redis://127.0.0.1:6379/0`) or how to start them. The quickstart
  has a "Without Docker" section with the Homebrew and apt steps.
- **An edit form keeps a stored file without asking for it (@karni/ui).**
  `ResourceForm` no longer marks a file or image field "required" on edit
  when the row already has a file. The current file stays listed by name,
  and saving without a new one keeps it.
- **The sign-in page leaves the sidebar after sign-in.** The scaffold's
  `layout.tsx` (and the example apps') lists a `.../login` route only while
  nobody is signed in.
- **Fixes in the scaffold and docs.** The scaffold's README linked to
  `github.com/karni`, which is not Karni. It now links to the repository, and
  `python -m karni.links check` catches the ownerless form too.
  `docs/testing.md` opens with the four fixtures most tests use.

## 0.4.0 (2026-10-22)

- **PostgreSQL is the default, everywhere.** `pip install karni` now brings
  the PostgreSQL driver (`psycopg[binary]`), and the quickstart runs on
  PostgreSQL: `docker compose up -d --wait db` starts the project's own
  PostgreSQL 16, which a new project's `docker-compose.yml` now publishes on
  localhost only (`KARNI_DB_PORT` changes the port). SQLite is the no-Docker
  alternative, one `DATABASE_URL` away, without the guarantees only
  PostgreSQL gives.
- **Focus follows navigation, and a table is one Tab stop (@karni/ui).**
  `Layout` moves focus to the new page's heading after a client-side route
  change and announces the page title. It stays put on the first load, when
  only search params change, and when the page took focus itself.
  `routeFocus={false}` turns it off. `ResourceTable` is a WAI-ARIA grid with
  a roving tabindex: Tab enters and leaves the table, arrow keys move between
  rows and cells, Enter opens a row and Space toggles its selection. A 50-row
  page went from 205 Tab stops to 1. The table's role is now `grid`, and
  `keyboardNavigation="native"` restores the plain table.
- **OpenAPI enums are named after their model and field.** Two choice fields
  with the same name but different choices no longer get hash names such as
  `Status469Enum`. `karni.api.schema.postprocess_schema_enums` names them
  `<Model><Field>Enum` (`RefundStatusEnum`), with the app label in front when
  two apps have a model of the same name. `ENUM_NAME_OVERRIDES` still wins,
  and drf-spectacular's own hook restores its names.
- **The modules are tested on PostgreSQL.** CI runs karni-payments,
  karni-approvals and karni-impersonation on PostgreSQL 16 on every Python
  version, through the same overlay as the core. A pending change in
  karni-approvals now lists its fields in the model's order on PostgreSQL
  too (`jsonb` stores keys shortest first).
- **Scaffold comments in plain sentences.** The comments and the description
  in a new project's files no longer use em dashes.
- **Messages in plain sentences.** What the framework, the `karni` command,
  the modules and @karni/ui print or show (errors, system checks, `karni why`,
  `karni queries`, the query log, test helper failures, admin pages, emails,
  UI status text) no longer uses semicolons or em dashes. A few formats
  changed: the query log reads `GET /path 200: 3 queries, 2 duplicated`, a
  budget overrun reads `ran 28 queries against a budget of 8`, and
  `karni explain -` still recognises both the old and the new forms. A CLI
  error that ends in a command prints its docs link on the next line.
  Empty values show Django's `-` in the admin and `EmptyValue` in @karni/ui
  (`Select`'s default clear label and `DataChart`'s missing values). Tests in
  a project that match the old wording, or the old dash option label, need
  the new text.
- **Saving your prompts, suggested once.** The one-time tip in
  `karni doctor` and `karni check` now says what Gigai Chronicle is for (it
  keeps every prompt you give an agent, and `karni context --with-history`
  reads it back) and how to install it. It still says it is by Karni's
  author, still appears once per project, never in CI, and
  `karni config set suggest_tools false` silences it. The README, the AI
  guide and a new project's README mention it as optional.
- **AI visibility baseline.** `scripts/ai-visibility-check.md` records the
  first run (2026-10-22): Karni appeared in 0 of 10 questions with web
  search and 0 of 10 without, and a search for its own name found no Karni
  page yet.

- **Plainer wording across the docs, error codes, CLI help and agent files.**
  The documentation, the error code explanations and fixes, `karni --help`,
  the settings reference, the agent rules and procedures, and the header of
  the generated AGENTS.md and its siblings no longer use semicolons or em
  dashes, and read as plain sentences. No code, setting or command changed.
  Error code entries are headed `E104: title`. Run `karni rules sync` to
  pick up the new adapter wording. EventHub measures 619 lines of project
  code (the restore listener added 4).
- **Fixed: exporting a nested relation crashed.** A serializer that nests
  related rows (`many=True`, or `?expand=`) made CSV and XLSX exports fail
  with `TypeError: unhashable type: 'dict'`. Nested rows now export by the
  related model's natural key, the same as a plain relation.
- **Fixed: restoring a deleted row skipped its listeners.** New
  `karni.events.on_restored`, the counterpart of `on_deleted`. It runs inside
  the restore's transaction, so a listener that raises undoes the restore.
  `SoftDeleteModel.delete()` and `restore()` now run in a transaction with
  their listeners. The admin's delete and restore actions now go row by row,
  so `on_deleted` and `on_restored` run there too (they used one bulk
  `UPDATE` and fired nothing). A row a listener refuses is reported and the
  rest are restored. EventHub uses this to take a restored booking's seats
  again. A sold-out tier refuses the restore with E985.
- **Fixed: duplicate OpenAPI operation IDs.** `GET <resource>/import/` and
  `GET <resource>/import/{job}/` shared one ID, and so did the two
  effective-permissions routes, so generated clients got `_retrieve_2`
  names. A route that ends in a path parameter now gets `_by_<param>`, for
  example `events_import_by_job_retrieve`. Clients generated from the schema
  rename those two functions. The standard detail IDs do not change.
- **Fixed: booking one slot at the same moment could fail with a 500.**
  PostgreSQL sometimes settled several concurrent writes against a
  `no_overlap` constraint with a deadlock instead of the overlap error.
  Writes to one resource (one room, say) now take turns through a
  transaction-scoped advisory lock, so the second writer sees the first
  one's row and gets the 409 (E984).
- Query budgets no longer count `SAVEPOINT` statements or those advisory
  locks. They come from `transaction.atomic()` nesting and locking, not from
  reading data.
- **Typed fields: the database enforces what a value is (`karni.fields`).**
  `MoneyField` (NUMERIC(19,4), a declared currency, floats refused with
  `E962`, a declared rounding rule, and `quantize`/`split`/`allocate` that never
  lose a cent), `PercentField` and `QuantityField` (CHECK bounds),
  `EmailField` (unique on `LOWER(email)`), `SlugField` (generated,
  collision-free), `PhoneField` (E.164 CHECK), `CountryField`/`CurrencyField`
  (CHECK against shipped ISO 3166-1 / ISO 4217 lists), `JSONField(queried=True)`
  and `ArrayField` (GIN), and `SearchField` (a generated tsvector with a GIN
  index the default search provider matches through). Unique Karni fields and
  the new `LiveUniqueConstraint` are partial on soft-deletable models, so a
  deleted row frees its value. Every guarantee is proven with raw SQL on
  PostgreSQL and, where portable, SQLite. New checks: `E960` (a FloatField
  named like money fails boot), `W965` (CASCADE on a financial or audited
  model), `E964`/`W964` (a field or guarantee the configured database lacks),
  `W967` (a searched, filtered or ordered column without an index), plus
  `E961`, `E963`, `E968`, `E970`. `class Karni:` gains `append_only` (BRIN),
  `cascade`, `financial` and `not_money`. `karni schema` (`manage.py
  karni_schema`, `--json`) lists every column, constraint and index, why it
  exists and whether the database has it. `karni.accounts` 0005 creates
  `btree_gist`, and `CreateExtension` names the exact SQL (`E966`) when the role
  may not. `karni make model` gains `money[:EUR]`, `percent`, `quantity`,
  `email[:unique]`, `slug[:source]`, `phone`, `country`, `currency`,
  `json[:queried]` and `array:<type>` (`email`, `slug` and `json` now write
  the Karni fields). Rule K114. See [docs/fields.md](docs/fields.md).
- **Lifecycle columns and limited resources, enforced by the database**
  ([docs/lifecycle-and-capacity.md](docs/lifecycle-and-capacity.md)).
  `karni.fields.StateField(states=..., transitions=...)` declares a status
  column's states (a `CHECK` on the column) and its legal moves:
  `row.transition("status", "confirmed")` or assignment + `save()` is checked
  against the state the row was loaded with (`E980`, `E982`, a 400 in the
  API), written with a conditional `UPDATE ... WHERE status = <loaded>` so two
  concurrent transitions never both succeed (`E981`, a 409), recorded in the
  change log (action `transition`) and announced by
  `karni.lifecycle.state_changed` / `@on_transition`. The OpenAPI schema
  carries `x-karni-transitions` and `x-karni-initial`.
  `karni.fields.CapacityField(total=...)` is a counter the database keeps
  between zero and its total, consumed only with `karni.capacity.reserve()` /
  `release()` (a locked, conditional `UPDATE`, with `E985`, a 409, naming what
  is left). `class Karni: no_overlap = NoOverlap("room", "during", ignore=...)`
  adds a PostgreSQL `EXCLUDE USING gist` constraint (creating `btree_gist`
  when first applied) that ignores soft-deleted and released rows (`E984`, a
  409 naming the existing row). Off PostgreSQL it is not enforced and
  `karni.W980` says so. New: `karni.fields.DateRangeField` /
  `DateTimeRangeField`, `karni.models.GuardedModel` (part of `BaseModel`),
  `karni make model` types `state`, `daterange`, `datetimerange` and
  `capacity`, agent rules `K115` and `K116`, codes `E980`–`E988`, `W980` and
  `C370`–`C372`. EventHub's ticket tiers and bookings use them (619 lines of
  project code, measured).
- **`karni why`: an access decision explained by the code that makes it.**
  `karni why events/<id> --as alice@example.com [--action update]`,
  `karni why events.<field> --as ...`, `karni why-empty events --as ...` and
  `karni why 403 <request-id>` (a request the dev server recorded) print the
  user and roles, the grants that applied and where each comes from, the gate
  and every part of `read`/`write` against the row, the row's values
  (redacted like the change history), the result, `file:line` and one
  concrete fix. It adds `--json` for agents, `why`/`why_empty` on `karni mcp`,
  and rule `K015`. The verdict comes from running DRF's own gate and lookup in a
  rolled-back transaction while the access layer records its decisions
  (`karni.api.access.trace`). `Predicate.explain()` takes a predicate apart
  with the same folds `|` and `&` use. A test matrix checks the verdict
  against the API for every user, viewset, action and row of the test app.
  New: `karni.why`, `manage.py karni_why`, `BaseViewSet.base_queryset()`,
  `karni.vetoes.first_veto`, `karni.accounts.roles.grant_rows` /
  `grant_sources`, and codes `E901`–`E908`, `C310`–`C312`. See
  [debugging](docs/debugging/why.md).
- **Debugging: one request id everywhere, a development capture, and
  `karni trace` / `karni replay` / `karni explain --failure`.** Every
  request gets an id (`X-Request-ID` on the response, where a client's value is
  accepted only in development or from a trusted proxy,
  `KARNI_REQUEST_ID_TRUST_HEADER`) that follows its Celery tasks and their
  retries (a message header), its email (`X-Karni-Request-ID`), outgoing
  calls (`karni.tracing.outgoing_headers()`) and the change log
  (`ChangeLog.request_id`, `ChangeBatch.request_id`, migration
  `karni_audit.0003`). With `DEBUG` on, Karni writes `.karni/requests/`,
  `.karni/failures/` and `.karni/trace/` under the project, bounded
  (`KARNI_DEBUG_CAPTURE_KEEP`, `KARNI_DEBUG_TRACE_DAYS`) and redacted by
  the change log's rules plus known secret values. With `DEBUG` off nothing
  runs. `karni trace` follows a request through its async work in order,
  `karni replay [--as USER]` re-runs it against the current code (rolled
  back unless `--commit`), and `karni explain --failure` turns a crash into a
  brief. The same three are MCP tools and agent rules K030–K032. New codes
  E920–E924, W920, C320–C323. karni-payments links a webhook delivery to
  the checkout it settles. See [debugging](docs/debugging/capture.md).
- **Debugging: `karni explain -` and `karni queries`.** `karni explain -`
  reads a pasted traceback, test failure or log line (stdin) and names the
  Karni failure in it: a registered code, an agent rule, a query-count
  failure, a CSRF/CORS refusal, an access outcome or a documented
  framework-adjacent failure (driver, database, migrations, settings, Redis,
  OpenAPI), with the cause, the first project frame, the fix and the docs
  link, or says plainly that it does not recognise it. `karni queries
  <endpoint> --as <user>` runs one endpoint in-process (writes rolled back),
  records every SQL statement with its stack and groups the repeated ones by
  the serializer field and relation behind them, with the optimiser's reason
  and the exact hint (`--json`, `--explain`, `--all`). The optimiser now
  records its blind spots (`karni.api.optimizer.blind_spots`). MCP tools
  `explain_text` and `queries`, agent rules K013 and K014, and codes E940–E943,
  C340, C341. See [debugging](docs/debugging/explain.md).
- One brand across the welcome page, the admin and `@karni/ui`: the same
  colours in light and dark, radius, font stack and dark-mode switch (the
  `dark` class on `<html>`, following the system preference by default). The
  `karni` package ships `@karni/ui`'s token stylesheet as the static file
  `karni/tokens.css`, a byte-for-byte copy that a test keeps identical. The
  admin loads it through `UNFOLD["STYLES"]` with `karni/unfold-theme.css`.
  In the admin, unfold's primary scale and text colours now read the tokens (`@karni/ui`'s
  near-black primary in light mode, near-white in dark, replacing the indigo
  scale), its neutral scale holds the tokens' gray values, `BORDER_RADIUS` is
  `var(--karni-radius-md)` and the font is `@karni/ui`'s system stack instead
  of Inter. Retheme the admin like the frontend, with `--karni-*` overrides in
  a stylesheet appended to `UNFOLD["STYLES"]` ([admin](docs/admin.md#theming)).
  The welcome page inlines the tokens instead of its own palette. Karni's
  admin pages (import, permission matrix, effective permissions) share
  `karni/admin-pages.css`, with no colour literals and no dark-mode duplicates.
  On a tablet the matrix shows several roles beside a narrower model column,
  the template downloads and the effective-permissions link are 44px buttons,
  and on touch screens unfold's sidebar rows, inputs, selects and save buttons
  are 44px. The hard-delete confirmation uses unfold's layout and buttons (its
  buttons rendered as plain text). Account emails use the brand's colour values.
- `@karni/ui` forms: `ResourceForm` validates when a field loses focus (not
  per keystroke, and `validationMode` / `reValidateMode` change it), puts every
  DRF error shape on its field, shows a focusable summary when more than one
  thing fails, words 401/403/409/429/5xx and offline failures in a banner with
  "Try again", never loses typed input, shows a skeleton shaped like the form,
  "You can't edit this event" on a 403, disables the fields while saving
  (`PendingButton`), submits with Enter and Ctrl/Cmd+Enter, autofocuses on
  create, and wires labels, `aria-invalid`, `aria-describedby` and
  `aria-required` for every field kind. Unsaved changes: `beforeunload` while
  dirty (`guardUnsavedChanges`), `onDirtyChange`, and
  `useUnsavedChangesGuard` for a router's blocker. New `slots`
  (`defaultResourceFormSlots`), `submitLabel`, `autoFocus`, `resourceLabel`.
  Fixed: an empty optional email or URL field no longer blocks the submit, and
  a created form now starts over after saving (it kept the typed values).
  `ResourceSelect` pages through the API instead of showing one page (scroll,
  "Load more", keyboard), renders only the rows in view, keeps results while
  a search loads, says when search is unavailable, tells "no venues yet" from
  "no match", has loading, error, 403 and offline states, labels preselected
  ids in one `?id__in=` request where the API has it, never shows a bare id,
  forwards its ref and takes `onBlur`, `aria-*`, `slots`
  (`defaultResourceSelectSlots`), `searchable`, `idsFilter`. Input, Textarea,
  Select, Checkbox, Switch and FileUpload draw `aria-invalid` with the
  destructive tokens. `Select` and `FileUpload` take `aria-describedby`,
  `aria-invalid` and `onBlur`. A slow `PendingButton` keeps its accessible
  name. `useSchema` returns `refetch` and `isFetching`.
- `@karni/ui` unhappy-state kit: `describeError` words any failure in plain
  words (never a status code), `ErrorState`, `PermissionDenied`,
  `PendingButton` (progress after 500ms, keeps its width), `useDelayedFlag`,
  `useOnlineStatus`. Dark mode for apps: `ThemeProvider`, `ThemeToggle` and
  `KARNI_THEME_SCRIPT` (follows the system until the user chooses), and
  `karniTheme()` from the new `@karni/ui/vite` entry, which puts the script
  first in `index.html`'s `<head>`. A project from `karni new` has all of it
  wired, with the toggle in the sidebar footer.
- `karni ui detect`: adopts the frontend's design system as `@karni/ui`'s
  tokens, in one file the project owns (`karni-theme.css`, imported after
  `@karni/ui/styles.css`). shadcn/ui: every token references the project's
  own variable (`var(--primary)`, or `hsl(var(--primary))` for Tailwind 3
  HSL channels) on `:root, .dark`, and `karni-primitives.tsx` registers the
  project's shadcn components as Karni's primitives. Otherwise a Tailwind
  theme (`@theme`, or the `tailwind.config` Node evaluates), a Material UI,
  Chakra UI or Mantine theme (literal values read statically), or Karni's
  defaults listed for editing. The report lists every token mapped and every
  value not mapped with the reason (`--json` for agents, `--dry-run` to
  preview). An edited file is never overwritten without `--force`. New error
  codes C301-C304. `karni new` does not write the file (nothing to detect in
  a fresh project). See [docs/theming.md](docs/theming.md).
- `@karni/ui` ResourceDetail, ResourceImport, ChangeHistory, LoginForm and
  AuthGuard handle every unhappy state through the kit, each with `slots`
  (and `defaultXSlots` to wrap). ResourceDetail shows a loading placeholder in
  the record's own layout, header included (no layout shift). A 404 shows
  "Couldn't find this event" (worded so an out-of-scope record is not
  confirmed to exist) with a `back` action, and a 403 shows "You can't view
  this event". Retry refetches the schema when that failed, and offline
  reloads by itself. `title`/`actions` may be functions of the record. Edit
  and Delete come with `onEdit`/`canEdit`, `enableDelete`/`canDelete`/`onDeleted`
  (delete asks first and reports a refusal in the dialog). A field the role
  may not read has no row at all. An empty value is the new shared `EmptyValue` (an en
  dash read as "empty"), also used by ResourceTable (which now treats `""`
  as empty) and ChangeHistory. ResourceImport shows no form when the role may
  not import, keeps the file after a failed upload, confirms a commit with
  its counts, announces progress by the quarter, and its tables have
  captions and header scopes. LoginForm tells wrong credentials from
  throttling, server errors and a dropped connection, wires the message to
  the fields and focuses the email (`autoFocus`). AuthGuard can explain a
  refusal (`explain` gives a sign-in prompt for anonymous visitors and
  PermissionDenied for a role without access, and `anonymous`/`denied` replace
  one case). Deprecated: a guard with no `fallback` and no `explain` still
  renders nothing, as in 0.3, and warns once in development. Version 1.0 makes
  `explain` the default (`fallback={null}` keeps rendering nothing).
  Behaviour changes: a non-HTTP sign-in failure no longer reads as wrong
  credentials. ResourceDetail's empty dash is "–" (was "—"), and its error
  panel no longer shows a raw error message.
- `@karni/ui` primitive registry: `<KarniProvider primitives={{ button: Button,
  input: Input, select: {...} }}>` renders every Karni component with the
  project's own primitives (roles `button`, `input`, `textarea`, `checkbox`,
  `switch`, `label`, `skeleton` and the `select` family), keeping Karni's
  schema-driven behaviour. shadcn/ui's components fit the contract as they
  are. `KarniPrimitivesProvider` and `useKarniPrimitives` are exported.
- `@karni/ui` design tokens: every visual value in every component now
  resolves from a CSS custom property in `--karni-color-*`, `--karni-space-*`,
  `--karni-radius-*`, `--karni-font-*` or `--karni-shadow-*` (plus stacking,
  opacity, motion and line widths). The preset maps Tailwind's scales onto
  them, so one stylesheet rethemes every component. Colours take any CSS
  colour. Motion drops to 0ms under `prefers-reduced-motion`. New ESLint rule
  `karni/no-style-literals` and a test that compiles every component class
  keep literals out, and `npm run build` runs the lint. Every Storybook story
  renders pixel-identical before and after, light and dark. The 0.3 HSL
  triplet names (`--karni-primary`, ...) still work and are deprecated
  ([docs/migrations/0.4.md](docs/migrations/0.4.md)). ResourceDetail's section
  background now uses the shared `muted-subtle` shade (50% muted, was 40%).
- `@karni/ui` app shell, keyboard and screen readers: `Layout`, `Page`,
  `Modal`, `Toaster`, `EmptyState`, `Stat`, `DataChart` and `FileUpload` take
  `className` and `slots` (`slots={{ NavLink: RouterLink }}`), with exported
  slot contracts and `default*Slots`. `ModalTitle` and `ModalDescription` are
  exported. Layout's mobile drawer is a modal dialog (focus trapped and
  returned to the menu button, Escape closes, labelled) and the shell starts
  with a skip link. Nav links, SelectTrigger and the toast close buttons show
  a keyboard focus ring. Toasts are announced by urgency (errors assertive)
  and pause while hovered or focused. FileUpload announces refused files,
  takes `error`, `uploading`, `aria-invalid`, `aria-describedby` and
  `aria-labelledby`. DataChart is focusable (the arrow keys read point by
  point), gets a generated summary and `loading`, and keeps its axis labels
  legible on phones. Stat takes `loading`, and a zero delta reads "Unchanged"
  (it read "Increased by +0"). `Input`, `Textarea`, `SelectTrigger` and
  `Checkbox` show a destructive border under `aria-invalid`. Contrast: token
  values change so every pair the components use reaches WCAG AA in both
  themes (in light `muted-foreground`, `destructive`, `input`, `chart-2` and
  `chart-3`, in dark `destructive`, `destructive-foreground` and `input`), checked by
  a new test, and the dark theme's modal and drawer scrim dims the page (it
  lightened it). axe-core runs over every Storybook story in both themes in
  CI (WCAG 2.x A and AA) and fails the build on any violation. A story turns
  one rule off only with a written reason. Dialogs are never taller than the
  viewport (they scroll inside), and a busy pagination button keeps its name.
- `@karni/ui` ResourceTable in every state and at real size. Each state is its
  own screen and a replaceable slot (`slots`, `defaultResourceTableSlots`):
  a loading outline of the real layout (nothing moves when data arrives),
  "No events yet" with the create action (`onCreate`, `createLabel`) apart
  from "No events match" with "Clear filters", errors in plain words with a
  retry, a failed refresh that keeps the rows, "You can't view events" for a
  403 (4xx are no longer retried, except 408 and 429. Anything else retries as
  the app's QueryClient `retry` default says, so `retry: false` shows the
  error at once), offline, and progress
  after 500ms with controls that do not double-fire. Row actions follow the
  schema's `x-karni-access` rules for the signed-in user (`canCreate`,
  `canEdit`, `canDelete` override). Delete failures are reported (row delete
  now confirms in a dialog instead of `window.confirm`). Bulk actions confirm
  destructive work with the count, may return `{ failed: [{ id, reason }] }`
  to mark failed rows, and show progress. Page, page size, sort, search and
  filters live in the URL (namespaced, and Back works), with `syncUrl`,
  `urlNamespace` and `stateStore` for a router. There is a page size
  choice, first/last and jump to page. Wide tables scroll in their own box with
  a sticky header and a frozen first column. Compact rows and hidden columns
  are remembered per user. Below `cardBreakpoint` (the table's own width), rows
  render as cards. Rows open
  from the keyboard, checkboxes are named after their row, and page, sort,
  selection and loading changes are announced. The parsed schema now carries
  each operation's `access` rule. Changed wording: the empty screen says "No
  events yet" (was "Nothing here yet"), the select-all checkbox "Select all
  events on this page", row checkboxes "Select <row>", filter "All" items
  "Status: All", and list errors read like every other error ("Something went
  wrong on our side", "Try again").
- The README opens with why Karni exists, then says what problem it solves,
  how, what you get and what you still write. The canonical description now
  leads with the same framing (your agent writes only your domain, and the rest
  is a package you upgrade) on the GitHub About, PyPI, npm, the docs homepage,
  the FAQ and llms.txt. `scripts/check_description.py` also checks the FAQ's
  first answer and the README's first two sections (order, the story's
  180-word limit, the four answers in order, no marketing words), and writes
  the homepage's description quoted.
- All five Python packages (`karni`, `karni-cli`, `karni-payments`,
  `karni-approvals`, `karni-impersonation`) are on PyPI (0.3.1). The README's quickstart installs them with a plain `pip install`.
- **Security: a row outside the requester's row scope stays hidden on every
  response.** An audit probed row-scope denials (a user who may list a
  resource but not one row in it). The row itself was already treated as
  missing everywhere (404 on detail and the write verbs, absent from lists,
  filters, search, ordering, exports and the admin). Four paths leaked
  *related* rows and are fixed:
  - A write's response (`PATCH`/`PUT`/`POST …?expand=`), and any response of
    a viewset with `optimize = False` or a `select_related` /
    `prefetch_related` hint, embedded related rows (and listed to-many ids)
    outside the target's read scope. The generated serializers now check
    related rows at render time (`karni.api.related`): no extra query on the
    optimised path, one per related model and page otherwise.
  - An export named an unreadable related row by its natural key (a venue's
    name where the API shows only its id). It now keeps the id, and the
    admin's export names related rows as far as the admin's row scope shows
    them.
  - `?ordering=` on a to-many relation repeated each row once per related
    row, readable or not (and pushed others off the page), and on a forward
    relation sorted by the related model's `Meta.ordering`. Behaviour change
    for API clients: to-many and reverse relations are no longer orderable
    by default, and `?ordering=<relation>` sorts by its key column. An
    explicit `ordering_fields` is unchanged.
  - A relation in explicit `filterset_fields` filtered by the key of a row the
    requester cannot read (200) but refused a missing one (400). Its choices
    are now the readable rows (`KarniFilterSet`), so both answer 400.
- `karni.testing.assert_row_hidden(client, "/api/events/", row, visible=…)`
  proves in one line that a row outside the client's row scope behaves as
  "does not exist" on every API surface: detail and write verbs (compared
  with a missing key), detail actions, the list and its count, filters,
  search, ordering, `?expand=` and id lists from every related resource
  (writes included), and every export format.
  `assert_admin_row_hidden(staff, row, visible=…)` does the same for the
  admin's changelist, change, history and delete views. Each check runs on
  its own (`checks=["export"]`), `probe=` takes a `HiddenRowProbe` subclass,
  and a run that proves nothing (the client cannot list, or sees no row)
  fails with the new code `E616`. `assert_isolated` now runs the same probe on
  the other principal's row (and probes PUT, where a 403 on a write passes only when
  a missing row gets 403 too), so tests `karni make test` writes get it
  without a change.
- `karni check` exits 1 when only eslint fails (a raw `<table>` in a page, any
  `karni/*` rule). It printed `FAILED` but exited 0, so CI let it through.
- `karni` commands no longer end in Django's traceback when the project's
  database is not ready. On the host, a command that starts Django first
  checks that the database driver loads, and one that opens the database
  (`migrate`, `seed`, `sync-roles`, `createsuperuser`, `serve --local`,
  `test`, `beat`, `manage`) that the server answers. A missing driver is
  `C012` (install `psycopg[binary]` into the project interpreter, or use
  Docker) and an unreachable database is `C013` (with the address, the
  driver's error, and a note when `.env` is missing or `db` is the compose
  host). Captured commands (`karni context`, `karni types`) are checked only
  after they fail, so they cost nothing when the project works.
  `KARNI_DB_CHECK=false` skips the check. `karni check` still runs the
  frontend checks when the backend cannot start.
- Releases can publish npm with an `NPM_TOKEN` repository secret instead of
  trusted publishing, like `PYPI_API_TOKEN` for PyPI ([releasing](docs/releasing.md)).
- The `karni` command as a container image, `ghcr.io/cbsshekhawat18-lab/karni`
  (linux/amd64 and arm64), built from the PyPI release after every release
  and listed under the repository's Packages. It runs the CLI on machines
  without Python 3.12: `docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/work"
  ghcr.io/cbsshekhawat18-lab/karni new "Ticket Shop"`.
- `karni`, `karni-cli`, `karni-payments` and `karni-approvals` are on PyPI
  (0.3.1). The README's quickstart installs them with a plain `pip install`.
  Installing from a checkout is for unreleased changes only.
- `@karni/ui` and the three module UIs are on npm (0.3.1). The README's
  quickstart installs the frontend with a plain `npm install`, and `karni new`
  no longer says `@karni/ui` is unpublished.
- Tailwind 4 for new projects: `karni new` sets up Tailwind 4 through
  `@tailwindcss/vite`, loading the same `@karni/ui` preset with `@config`, and
  Vite 8. New `@karni/ui/tailwind-v4.css`, imported after Tailwind in a
  Tailwind 4 project, keeps a bare `border` on the `--karni-border` token.
  `@karni/ui` keeps working with Tailwind 3: every Storybook story (light and
  dark) and every page a new project generates render pixel-identical under
  Tailwind 3 and 4. The form and sign-in field gaps no longer use `space-y`
  (Tailwind 4 moved its margin onto the inline label, which ignores it).
- Development tooling: Vite 8, Vitest 5, Storybook 10 (with
  msw-storybook-addon 3) and Tailwind 4 in `@karni/ui` and the module UIs.
  CI and releases run on Node 24 (Node 20 is out of support, Vitest 5 needs
  22.12 or later, and npm trusted publishing needs npm 11.5). The Pages and
  artifact actions are on their current majors. `npm audit` reports nothing, dev
  dependencies included.

## 0.3.1 (2026-10-20)

A patch release: security updates to the development tooling, Vite 6.4 for
new projects, and publishing to PyPI. No public API changes.

- The release workflow publishes to each registry separately:
  `KARNI_PUBLISHING` names the registries that are set up (`pypi`, `npm`,
  `pypi,npm` or `true`), and PyPI uploads one project at a time, core first,
  with `skip-existing`, so a missing trusted publisher cannot half-publish a
  release. The GitHub release carries the npm tarballs too.
- Development tooling upgraded, closing every Dependabot alert (52, all in
  build and test tools, none in what the packages ship): Vite 6.4, Vitest 4.1
  (which drops tinypool), vite-plugin-dts 5 (API Extractor, and with it
  sprintf-js, is no longer installed), typescript-eslint 8 in the module UIs,
  and overrides for `uuid` (Storybook 8) and `postcss-selector-parser`
  (Tailwind 3). New projects get Vite 6.4 and the same override. The
  generated type declarations and Tailwind's output are unchanged. Vitest 4
  hands a jsdom `FormData` to Node's fetch without file names, so the UI test
  setup restores them the way a browser sends them.

## 0.3.0 (2026-10-20)

See [docs/migrations/0.3.md](docs/migrations/0.3.md) for the two breaking
changes and how to upgrade.

- Membership scoping and generated tests, from the social-leads practice project:
  `own` takes an owner path through a many-to-many
  (`owner_field = "workspace__members"`), now documented as the way to scope
  rows to a workspace's members. The test factories accept one row for a
  many-to-many, so `assert_crud` and `assert_isolated` drive it. A new
  check, `E214`, resolves every path a role's grants filter on (owner paths,
  scope paths, custom scopes) at boot, so a scope that names a missing path
  fails `karni check` instead of answering 500. `karni make test` says, in
  its output and the test file, why it leaves `assert_isolated` out.
- Django 5.2 LTS: karni requires `Django>=5.2.8,<5.3` (5.1 is out of
  support, and pip-audit reported ten unpatched advisories against 5.1.15) and
  django-unfold 0.110. Python 3.14 is supported and tested. On Django 5.1,
  every admin page failed under 3.14. Projects pinned to Django 5.1 upgrade
  Django with karni. No project code changes were needed in EventHub,
  Social Leads or the modules. Dropping Django 5.1 is a minor-release
  change under the [stability promise](docs/stability.md), released as 0.3.0.
- `karni seed` can run again on a seeded database. Each run is a new process
  that draws the same UUID keys from the same seed, so a second run failed
  with `E612` on the primary key (found by running the README quickstart, then
  adding a model and seeding again). A key an earlier run used is now replaced
  by one derived from it. An empty database still gets the same rows.
- A generated reference: `scripts/gen_reference.py` writes `docs/REFERENCE.md`
  (every command, base class, `class Karni` key, setting, component, hook,
  module, error code, make target and slash command, with each capability's
  status) and the README's generated blocks from the source, and CI fails when
  either is stale. `karni.meta.OPTIONS` (and a module's `KARNI_OPTIONS`) now
  documents each `class Karni` key, and the generator fails on a key that code
  reads but no list declares. Every `@karni/ui` export has a one-line JSDoc.
- The README is rewritten: a demo recorded from a real quickstart run
  (`scripts/demo/`), a cheat sheet, the generated command table and per-area
  reference, an honest comparison and status. The quickstart (README and
  docs) adds `karni make page login --kind login`: a new project had no
  sign-in page for the React app. Package READMEs link absolutely, so their
  links work on PyPI.

## 0.2.0 (2026-10-20)

See [docs/migrations/0.2.md](docs/migrations/0.2.md) for every breaking
change and its migration note.

- Roles as data: `KARNI_ROLES`, `karni sync-roles`, `user.can()`,
  `@requires()`, `Can("app.model:action")` in `access` declarations
  (ADR 0002).
- Row-level scoping (ADR 0002, P2): `access = Granted()` is the default
  `karni make viewset` writes and scopes rows by the roles' grants. The
  admin shows only the rows the user's grants reach. `scope_exempt` takes a
  reason that `karni check` lists. `assert_isolated` gains the `grant`
  dimension and probes expansion, filters, search, ordering and the admin.
- Welcome page: `/` on first boot (`karni.welcome.welcome_urls()`, mounted
  last by the scaffold) shows the project live: models with admin and API
  links, modules, seven status checks each with the command that fixes a
  cross, the `karni context` output and the first agent prompt. It is `DEBUG`
  only and gone once the project owns `/`, and `karni.E505` guards production.
- Field-level visibility (ADR 0002, P3): `class Karni: field_roles` hides
  fields per role on the API (absent, never `null`), in `?expand=`, in the
  per-role OpenAPI schema and in the admin. Write-protected fields are
  refused naming the roles that may. `?ordering=`, filters and `?search=`
  ignore hidden fields. `@karni/ui` refetches the schema on identity
  change. `assert_crud` checks visibility. `?ordering=` now accepts only
  serializer-visible fields, `search_fields` may not name a write-only
  field (`E131`), and `E212` validates `field_roles`.
- Change history (ADR 0002, P4): the `karni.audit` app records, for models
  that opt in with `class Karni: audit = True`, who changed what from what
  to what, captured at the model layer so the API, admin, commands and the
  shell all leave the same entry. Sensitive fields are redacted. The history
  shows on the admin History tab, `GET /<resource>/<id>/history/` and
  `<ChangeHistory/>`. Retention pruning is off by default. `karni check` flags
  `update()`/`bulk_update()` on audited models (`audited-bulk-write`, `K113`).
- Permission matrix (ADR 0002, P5): Roles → *Permission matrix* in the
  admin changes who may do what with no deploy (roles across, models down,
  a scope selector per action, bulk selectors, a confirmation diff), with
  the guard rails (system roles keep their declared grants, nobody grants
  what they do not hold, nobody removes their own last permission to change
  permissions) and the matrix's own change history. *Effective permissions*
  answers "why can this person see this?" per user. The same is available as
  an API under `api/auth/permissions/` for custom UIs, fixtures and tests
  (`E213`). `RolePermission.origin` tells the sync which grants the matrix
  owns. Also new: `KARNI_MATRIX_EXCLUDE`.
- Import and export (ADR 0002, P6): `GET /<resource>/export/?format=csv|xlsx`
  on every resource (the list as the request sees it, filters and scope and
  field visibility included, relations as natural keys) and a four-step
  import (`/<resource>/import/…`): upload, map columns (remembered per model
  per user), the mandatory dry run with exact counts and per-row errors,
  then one transaction recorded as one audit batch. Large files run in
  Celery with progress. Per-model hooks live in `class Karni` (`natural_key`,
  `import_key`, `import_lookup`, `import_transform`, `after_import`), and
  there is a downloadable template per model. Every Karni admin gets export
  actions and an Import page, and `@karni/ui` gets `<ResourceImport/>` and
  export buttons on `<ResourceTable>`. Settings `KARNI_IMPORT_INLINE_ROWS`,
  `KARNI_IMPORT_MAX_ROWS` and `KARNI_EXPORT_MAX_ROWS`, codes `E801`–`E803`.
- Write interception: every `BaseModel` save and delete sends
  `karni.signals.pre_write`. A receiver that raises `KarniWriteDeferred`
  stops the write before any SQL: the API answers 202 with its payload, and
  the admin shows its message. The hook behind the new `karni-approvals`
  module (M1): `class Karni: requires_approval = [...]` turns a maker's
  guarded change into a pending change a second person approves or
  rejects (never the maker, in code), with per-model approvals count,
  approver roles and timeouts, an admin queue, `/api/pending-changes/`,
  Celery notifications, every decision in `karni.audit`, and
  `@karni/approvals-ui` (`<ApprovalsQueue/>`, `<ApprovalsBadge/>`).
- Vetoes: `karni.vetoes.register_veto` refuses an action at the API and
  admin gates after the access declaration admitted it (a maintenance
  freeze, a read-only tenant), plus `KarniAdminMixin.vetoed()`. The hook behind
  the new `karni-impersonation` module (M2): "log in as user" for support
  with an explicit `impersonate` permission never implied by staff status,
  no privilege escalation (a target holding anything the actor lacks is
  refused), a banner naming both identities with a one-click exit, a
  session record, every write attributed to both identities in
  `karni.audit` (the row's actor is the target, the batch's actor the
  impersonator), a configurable time limit, a hard block on deleting,
  exporting and payment changes while impersonating, the target notified
  and a reason required by default, a threat model in the README. Also new:
  `karni.audit.capture.within_batch`, `@karni/impersonation-ui`
  (`<ImpersonationBanner/>`) and `useAuth().adoptTokens` in `@karni/ui`.
- `karni check` and the architecture suite now scan a project's apps
  without `BASE_DIR` (the audit's "enforcement scans zero files" finding).
- The launch audit's remaining findings: `karni migrate` creates `pg_trgm`
  (`?search=` no longer 500s on a fresh PostgreSQL). `KARNI_CACHE=locmem`
  runs a project without Redis and the quickstart uses it, with pytest in
  its install line. `karni.welcome.media_urls()` serves uploads in
  development. Also fixed: `karni --version`, `karni doctor` with the venv
  outside the project, and `karni context` (and the MCP `context` tool) from
  the interpreter running karni-cli. `karni serve`/`karni worker` pass SIGTERM
  on to the server. `karni test` says when pytest is missing (`C011`).
  `karni check` runs the frontend's ESLint next to jscpd. The scaling check
  also measures every list with `?expand=`. A `KARNI_*` dotted path that
  cannot be imported is `E506` naming the setting (`E507` for `KARNI_CACHE`).
  Generated detail pages expand their relations. A required relation left
  empty says "Required" and an optional one clears. A new project's pyproject
  has `[tool.karni] baseline`, so `karni upgrade` never reports changes a fresh
  scaffold already satisfies. `LOGIN_REDIRECT_URL` defaults to the admin.
  The seed login says "superuser". The two schema warnings are gone. The
  cosmetics too: choice labels from the schema's choice list instead of raw
  markdown help text (`FieldDef.enumLabels`), one casing for every table
  header, `karni rules` trimmed (402 cl100k tokens, measured), and the
  admin's *All* rows counted once. The EventHub Playwright journeys ran
  (three passed) and every package built, installed into a clean venv and
  dry-run published.
- Every `BaseViewSet` declares `access`. Relation fields and `?expand=`
  follow the target's read scope. Query budgets fail tests.
- Errors that teach: every error carries a code, `karni explain <code>`,
  the generated error reference.
- `karni make …` generators and the project runners (`karni serve`,
  `migrate`, `test`, `seed`, …), and `karni upgrade` with codemods.
- The documentation site, the EventHub reference application, release
  automation, the brand assets.

## 0.1.0

The first cut: `BaseModel` and scopes, the `access` declaration, generated
serializers and viewsets, the derived admin, accounts, events and schedules,
`@karni/ui`, the scaffold and the agent adapters.

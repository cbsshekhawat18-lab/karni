---
description: "Karni's test tooling: the assert_crud, assert_isolated, assert_row_hidden and assert_pages one-liners, the pytest plugin, query budgets, the scaling check and the architecture rules suite."
---

# Testing

Karni ships the test tooling a project would otherwise write by hand, and
wires it in so that it runs without project code:

| Piece | What it gives you |
|---|---|
| [`APITestCase`, `client_as`](#clients-per-role) | an authenticated client per role, in one call |
| [`assert_crud`](#the-full-crud-surface-in-one-call) | the whole CRUD surface of a resource for a role, checked against its `access` declaration and the OpenAPI contract |
| [`assert_isolated`](#isolation-the-test-people-forget) | one line proving a role cannot see or touch another owner's rows |
| [`assert_row_hidden`, `assert_admin_row_hidden`](#hidden-rows-the-row-scope-check) | one line proving a row outside a client's row scope behaves as "does not exist" on every API surface, and in the admin |
| [`assert_pages`](#public-pages-assert_pages) | every page of a public site answers, has a title, a description and alt text, and links only to URLs that exist |
| [`assert_schema_snapshot`](#schema-snapshot) | an accidental API break fails CI |
| [`karni.testing.factories`](#automatic-factories-karnitestingfactories) | a valid factory-boy factory for any model, with realistic values. `<app>/factories.py` overrides it |
| [`karni.testing.performance`](#query-budgets-and-n1-karnitestingperformance) | the `query_budget` fixture, per-endpoint budgets that raise, the N+1 scaling check |
| the `karni` pytest plugin | loaded automatically (`pytest11` entry point) wherever `karni` is installed |
| [`karni.testing.architecture`](enforcement.md) | the build-failing architecture rules (and the scaling check) |

CI runs two invocations: the project's own suite (`pytest`) and Karni's rules
(`pytest --pyargs karni.testing.architecture`). Both need `pytest-django`
and a test database. `karni make test <Model>` writes a starting test file
like the one below.

## The fixtures you will use

Most project tests need only these four, and a project with a public site
one more:

- [`client_as(role)`](#clients-per-role): an API client signed in as a user
  with that role. `client_as(None)` is anonymous. It is a method on
  `APITestCase` and a pytest fixture.
- [`create(Model, **fields)`](#automatic-factories-karnitestingfactories):
  one saved row with every required field filled, from
  `karni.testing.factories`.
- [`assert_crud(ViewSet, role)`](#the-full-crud-surface-in-one-call): the
  whole CRUD surface for that role, checked against the viewset's `access`.
- [`assert_isolated(ViewSet, role)`](#isolation-the-test-people-forget):
  proof that the role cannot see or change another owner's rows.
- [`assert_pages(client, urls)`](#public-pages-assert_pages): each page of
  the public site answers 200 with a title, a description and alt text, and
  its links reach URLs that exist.

## A resource's full test, in 15 lines

<!-- karni:example:crud (tests/testing/test_docs_example.py runs this block) -->
```python
# events/tests/test_events.py
from karni.testing import APITestCase

from events.viewsets import EventViewSet


class EventAPITests(APITestCase):
    def test_full_crud_surface_for_organizers(self):
        self.assert_crud(EventViewSet, "organizer")

    def test_staff_get_exactly_the_promised_denials(self):
        self.assert_crud(EventViewSet, "staff")

    def test_organizers_never_see_each_others_events(self):
        self.assert_isolated(EventViewSet, "organizer")
```

That covers list, retrieve, create, update (PATCH and PUT) and delete for
two roles, every permission denial their `access` declaration promises,
pagination, filtering, the response contract, and owner isolation. The
viewset it tests:

```python
class EventViewSet(BaseViewSet):
    model = Event
    access = Access(
        read=Owned("organizer") | HasRole("staff"),
        write=Owned("organizer"),
        create=HasRole("organizer"),
    )
```

## Clients per role

Roles are Django groups (the same ones `HasRole(...)` checks), created on
demand:

```python
client = self.client_as("organizer")      # a user in the "organizer" group
client.user                               # that user
self.client_as("organizer").user == client.user   # same roles, same user, all test long
self.client_as()                          # signed in, no roles
self.client_as(None)                      # anonymous
self.client_as(user=alice)                # a user you made
```

Outside `APITestCase` (plain pytest), `from karni.testing import client_as`
works the same, and there is a `client_as` fixture.

## The full CRUD surface in one call

`assert_crud(resource, role)` (or `self.assert_crud(...)`) drives the
resource through its routed URLs as that role and checks:

- **list / retrieve / create / update / delete:** the status the resource's
  `access` promises the role. For allowed actions it also checks the effect:
  the created row exists with the sent values and the owner stamped from the
  requester, the update is stored, and the deleted row is gone.
- **Denials:** every action the role may not perform returns 401/403/404 as
  declared. A denial that *should* happen is a pass.
- **Pagination and filtering:** a list page has the paginator's shape, and
  declared filters actually narrow the result.
- **Visibility:** when `Karni.field_roles` hides fields from the role, they
  are absent from list and detail payloads and from the role's serializer
  (so from its schema), and a field the role may read but not write is
  refused on input naming the field. Skipped when nothing is hidden.
- **Contract:** every response is validated against the OpenAPI schema
  (types, enums, nullability, required fields, no undeclared properties).

A failure names what broke: the action, the expected and actual status, and
the field or check involved. `resource` can be the viewset class, the model,
or the route name.

### Files and images in the create body

A required `FileField` gets a small text upload named `<field>.txt`. A
required `ImageField` gets a 1x1 PNG made in memory with Pillow, named
`<field>.png` with the content type `image/png`, so DRF's image validation
accepts it. The body goes as multipart, and every request that carries it
(the create, the PUT and the denial checks) gets a fresh upload. The stored
file must not be empty, after the create and after the update. Optional file
fields are left out of the body. Without Pillow an image upload fails with
`E501`, which names `pip install 'karni[images]'`.

To send a file of your own, put it in `payload=`. It is rewound before each
request, so one object serves all of them:

```python
self.assert_crud(PhotoViewSet, "staff", payload={"image": my_upload})
```

### A role that may not write

When the declaration refuses create, update and delete to the role, the run
checks those refusals and passes, but it has made no successful write. The
report lists `no write exercised` in `skipped`, and `assert_crud` emits a
`UserWarning` naming the role and the declaration. Call it once more with a
role that may write, as the example above does with `"organizer"`. When the
refusals are the point of the test, pin them with `expect={"create": 403,
...}` and the warning stays quiet.

### Rows the role cannot see

When the rows `assert_crud` creates for the role are missing from the list,
because a read rule such as `Where(...)` scopes them out, the list and
pagination checks say so and point at `karni why-empty <resource> --as
<user>`, which names the step that drops them. The paginator is not blamed.

## Isolation: the test people forget

```python
self.assert_isolated(EventViewSet, "organizer")
```

Two users with the role each get a row of their own. The first must see
their own row (the positive control) and must not reach the other's through
any surface. The surfaces are checked in turn, starting with the list.
Retrieve, update (PATCH and PUT) and
delete must answer 404, never a 403 that confirms the row exists, and the
row must stay unchanged. A 403 passes only when the verb is refused for a
row that does not exist too. Then every check of
[`assert_row_hidden`](#hidden-rows-the-row-scope-check) runs on the other's row
(detail actions, filters, `?search=`, `?ordering=`, `?expand=` and lists of
primary keys from any resource relating to it, on reads and in write
responses, and every export format), with a row pointing at it created when
none exists. For the `grant` dimension the admin is checked too (the
changelist, its search, the change form and a POST to it), since the admin's
rows follow the roles' grants. Last, a create body naming another owner is
ignored and stamped with the requester. It runs for every isolation
dimension that applies. Two ship with Karni: `owner` (any `Owned(...)` read
path) and `grant` (a `Granted()` or `Can` read where the role's grant for the
model's `view` permission is `own` or `related:<key>`, with distinct related
values for the two users). A tenancy module adds `tenant` by registering a
dimension, and existing tests then cover it with no change. A resource no
dimension applies to fails and says why: `read=Authenticated()`, or a role
whose grant is `all`, lets every signed-in user see every row, which is
exactly the bug this catches. Probes that cannot run for a resource (no
admin registration, no export route) are listed in the report's `notes`.

## Hidden rows: the row-scope check

A denial is only reassuring when it comes from the row scope. A user with no
grant on a resource gets a 403 for every row alike, which proves nothing
about the user who *can* list the resource but must not see one row in it:
another owner's, one outside an `own` or `related:<key>` grant, one a
`Where(...)` leaves out. For that row, every surface must answer exactly as
it answers for a row that does not exist. `assert_row_hidden` checks it in
one line, for any client and any row your test sets up:

<!-- karni:example:hidden (tests/testing/test_docs_example.py runs this block) -->
```python
# events/tests/test_event_scope.py
from django.utils import timezone

from karni.testing import APITestCase, user_with_roles

from events.models import Event


class EventScopeTests(APITestCase):
    def test_another_organizers_event_is_hidden(self):
        me = self.client_as("organizer")
        mine = Event.objects.create(title="Mine", starts_at=timezone.now(), organizer=me.user)
        other = user_with_roles("organizer")
        theirs = Event.objects.create(title="Theirs", starts_at=timezone.now(), organizer=other)
        self.assert_row_hidden(me, "/api/events/", theirs, visible=mine)
```

Every check compares the hidden row with a primary key that does not exist:

| Check | The hidden row must |
|---|---|
| `detail` | answer GET, PATCH, PUT and DELETE like the missing key (404, never a 403 that confirms it exists), with the same error, and stay unchanged |
| `actions` | answer every `@action(detail=True)` (`history` included) like the missing key |
| `list` | not be listed. `count` must match the rows the pages hold, and `visible` (or some row) must be listed as the positive control |
| `filters` | stay out of every filter given its own values (and `?id=`). Another resource's relation filter naming it must answer like the missing key |
| `search` | stay out of `?search=` with a word of it. With `search="<term>"` (a term only the row matches), the search must find nothing |
| `ordering` | not change which rows or how many come back for any orderable response field (no row repeated or dropped). A model field the response does not show must not reorder the list |
| `expand` | not be embedded by any resource relating to it, through `?expand=` or a list of primary keys, on a read or in a `PATCH` response |
| `export` | not be written by `export/` in any format (also when filtered or searched for), nor named by its natural key in an export of a row pointing at it |

The admin counterpart checks that the changelist (and its search) leaves the
row out, and that the change, history and delete views, read or posted to,
answer exactly as Django's admin answers for a row that does not exist (a
redirect to the index, never a 403) and leave the row unchanged:

<!-- karni:example:hidden-admin (tests/testing/test_docs_example.py runs this block) -->
```python
# events/tests/test_event_admin_scope.py: KARNI_ROLES grants organizers "events.event:*": "own"
from django.utils import timezone

from karni.testing import APITestCase, user_with_roles

from events.models import Event


class EventAdminScopeTests(APITestCase):
    def test_the_admin_treats_another_organizers_event_as_missing(self):
        staff = user_with_roles("organizer", is_staff=True)  # the grant opens the admin page
        mine = Event.objects.create(title="Mine", starts_at=timezone.now(), organizer=staff)
        other = user_with_roles("organizer")
        theirs = Event.objects.create(title="Theirs", starts_at=timezone.now(), organizer=other)
        self.assert_admin_row_hidden(staff, theirs, visible=mine)
```

A leak fails with `E606` and one line per request that leaked, with the fix:

```
E606: assert_row_hidden(/api/events/, Event 0b5…): 2 problem(s) (6 checks passed)
  - detail: GET /api/events/0b5…/ answered 403 for the hidden row but 404 for a row that
    does not exist (a 403 confirms the row exists), expected 404: look the row up through
    the read scope before any permission check, as BaseViewSet.get_object() does …
  - expand: PATCH /api/venues/7c1…/?expand=events answers with the hidden Event 0b5…
    embedded: related rows in a response must be readable: …
```

A run that cannot prove anything fails too, with `E616`: a client that cannot
list the resource (a role-level refusal hides every row alike, and
`assert_crud`'s denials cover that), or one that sees no row at all.

- `resource` is the list URL, or anything `assert_crud` takes (the viewset,
  the model, the route name). `client` is an API client (`client_as(...)`)
  or a user. In plain pytest, `from karni.testing import assert_row_hidden,
  assert_admin_row_hidden`. The admin one takes a logged-in
  `django.test.Client` or the staff user.
- Each check runs on its own with `checks=["export"]`, and `skip=["expand"]`
  runs the rest. `formats=("csv",)` limits the export formats, `site=` names another
  admin site.
- Every check is a `check_<name>` method of `HiddenRowProbe` /
  `AdminHiddenRowProbe` (`karni.testing.hidden`). Pass a subclass as
  `probe=` to change one, or override `pointing_rows()` to choose (or
  create) the rows relating to the hidden one. The report lists probes that
  could not run (no export route, nothing relates to the row) in `notes`.

`assert_isolated` runs these checks on the other principal's row, so a test
`karni make test` writes already covers them. Reach for `assert_row_hidden`
when the scope is one `assert_isolated` cannot build two principals for (a
`Where(...)` on a status, a tenant, a custom scope), or to pin a specific
fixture.

## Public pages: assert_pages

A [public site](public-site.md) is HTML for visitors and search engines. Its
test requests each page the way they do and checks what they get:

```python
# website/tests/test_pages.py
from pathlib import Path

import pytest
from django.test import Client
from karni.testing import assert_pages, load_content
from pytest_django import Settings

PAGES = [
    "/",
    "/about/",
    "/services/design/",
    # karni:pages
]


@pytest.fixture(autouse=True)
def site_content(db: None, settings: Settings, tmp_path: Path) -> None:
    settings.MEDIA_ROOT = str(tmp_path)  # its images go to a folder the test owns
    load_content("content/site.json", missing_ok=True)


@pytest.mark.django_db
def test_every_page_passes_the_page_checks(client: Client) -> None:
    assert_pages(client, PAGES)
```

`karni make site` writes this test with `"/"` in `PAGES`, and `karni make
view` adds each new page's URL above the marker. A path with a capture, such
as `/services/<slug:slug>/`, needs a real URL, so the command leaves it to
you. The rows such a page shows come from the site's real content:
`load_content` loads `content/site.json` (what `karni design extract`
writes) the way `karni load` does, before each test. It reads a relative
path from the project root (`BASE_DIR`, else the folder above the settings
package), so the test passes whatever folder pytest runs in, and
`missing_ok=True` loads nothing until the file exists. A missing file is
`E804` and a row the models refuse `E805`, each with the path. Without a
content file, create the rows in the test, for example with
`create(Service, slug="design")` from
[`karni.testing.factories`](#automatic-factories-karnitestingfactories).

For each URL in the list, `assert_pages` checks:

| Check | The page must |
|---|---|
| status | answer 200. A redirect fails with its status and `Location`. `follow=True` checks the page it ends on instead |
| title | have a non-empty `<title>`. A `<title>` inside an inline `<svg>` names the drawing, so it does not count |
| description | have a `<meta name="description">` with a non-empty `content` |
| alt | give every `<img>` an `alt` attribute. `alt=""` marks a decorative image and passes |
| links | link only to same-site URLs that answer 200, or that redirect to a URL that answers 200 |

Once per call it also requests `/karni-assert-pages-404/`, a URL no site
has, and expects a 404. A catch-all route that answers every URL fails here,
because search engines would index its answers as real pages.

**Which links are checked.** Relative paths and absolute URLs on the test
host (`http://testserver/...`) are the site's own. They come from `href`,
`src`, `srcset` and `poster` attributes, so stylesheets, scripts and images
count as links. `mailto:`, `tel:`, `javascript:` and `data:` URLs, fragments
such as `#team` and other hosts are not requested, and neither is a redirect
to another host. Each distinct URL is requested once per call, and a page in
the list that answered 200 is not requested again when another page links to
it. A linked page gets the status check only. Put it in the list to give it
every check.

**Static and media files.** Django's test client serves no static files:
Karni's settings add no static route, and tests run with `DEBUG` off. So a
link under `STATIC_URL` that answers 404 is looked up with the staticfiles
finders, the lookup `runserver` and `collectstatic` use. A mistyped `{%
static %}` path fails and a file that exists passes. A link under
`MEDIA_URL` that answers 404 is looked up in the default storage when that is
the file system. Without `django.contrib.staticfiles` installed, static links
are listed in the report's `skipped` instead.

Every problem is reported in one `E618` error, one line per page and
problem:

```
E618: assert_pages: 4 problem(s) (2 page(s) and 5 link(s) checked)
  - /: a <meta name="description"> with an empty content attribute. Search results show
    it under the title. Give the page one sentence, in {% block description %} for a page
    that extends the site's base.html.
  - /about/: an empty <title>. Browser tabs and search results show the title. Give the
    page one, in {% block title %} for a page that extends the site's base.html.
  - /about/: 1 <img> without an alt attribute: /static/website/team.svg (line 25). Screen
    readers read the alt text and search engines index it. Describe each image in
    alt="...", or write alt="" when it is decorative.
  - /: links to /contact/ (line 25), which answered 404.
```

A request that raises stops the run, because the error may have left the
test's database transaction unusable. The failure names the request and the
exception, and the exception is chained, so its traceback shows too.

`assert_pages` returns a `PagesReport`: `pages` (the URLs checked as pages),
`links` (every distinct same-site link it requested or already knew),
`skipped` (checks turned off and links not requested, each with the reason)
and `failures`. An empty URL list is an error (`E619`), since it would pass
without checking anything.

Escape hatches:

- `follow=True` follows a page's redirects and checks the page it ends on.
- `require_title=False`, `require_description=False`, `require_alt=False`
  and `check_links=False` turn one check off. `not_found_url=None` skips the
  404 check, and `not_found_url="/other/"` names another URL.
- `ignore=[r"^/admin/", r"\.pdf$"]` takes regular expressions, searched in a
  link's path and query string. A matching link is not requested.
- `hosts=["www.example.com"]` names more hosts whose absolute links count as
  the site's own, for a template that writes the production domain.
- `parser=` takes a `PageParser` subclass (`karni.testing.pages`). Its
  `link_attributes` map a tag to the attributes that hold a URL, so a
  lazy-loading `data-src` can count as a link:

  ```python
  from karni.testing.pages import PageParser


  class LazyImages(PageParser):
      link_attributes = {**PageParser.link_attributes, "img": ("src", "srcset", "data-src")}


  assert_pages(client, PAGES, parser=LazyImages)
  ```

- In an `APITestCase`, `self.assert_pages(PAGES)` uses `self.client`.
  `client=` passes another one, for example a signed-in client for pages
  behind a login.

## Schema snapshot

```python
# tests/test_api_schema.py
from karni.testing import assert_schema_snapshot

def test_the_api_contract_is_unchanged(db):
    assert_schema_snapshot()
```

The generated schema is compared with `tests/openapi.snapshot.json`
(minus the integer bounds Django derives from the database backend, which are
32-bit on PostgreSQL and 64-bit on SQLite, so a snapshot written on one
matches CI on the other). A
difference fails, listing breaking changes (removed and changed paths) first.
A missing snapshot is written and the test passes, except under CI, where it
fails, because a snapshot that was never committed protects nothing. To
accept an intended change, run `KARNI_UPDATE_SNAPSHOTS=1 karni test`, then
commit the file. A `karni make` command that changes the API (`karni make
viewset`, `karni make form`, `karni make serializer`, `karni make model` for
a model a viewset serves, or with `--with viewset`) says so when the project
has a snapshot, with that command.

## Automatic factories (`karni.testing.factories`)

```python
from karni.testing.factories import build, create, create_batch, factory_for

event = create(Event)                        # every required field filled, FKs created
events = create_batch(Event, 5, venue=venue) # overrides as usual
draft = build(Event)                         # unsaved
EventFactory = factory_for(Event)            # a factory.django.DjangoModelFactory subclass
create("myapp.Event")                        # models can be named by label
```

`factory-boy` is a Karni dependency, so this works in every project.

### Resolution: explicit wins

`factory_for(model)` returns, in order:

1. an **explicit** factory: any `DjangoModelFactory` subclass defined in an
   installed app's `<app>/factories.py` whose `Meta.model` is the model. When
   one module defines several for a model, the one named `<Model>Factory`
   wins, else the first defined. Explicit factories are used everywhere: by
   `create()`, as the related-object factory inside generated ones, and by
   the scaling check.
2. a **generated** one (`auto_factory(model)`, cached per model).

```python
# myapp/factories.py (picked up automatically)
import factory
from factory.django import DjangoModelFactory

from myapp.models import Venue


class VenueFactory(DjangoModelFactory):
    class Meta:
        model = Venue

    name = factory.Faker("company")
    city = "Pune"
```

Discovery runs once per process. Call `karni.testing.factories.clear_cache()`
after adding a module at runtime.

### What a generated factory fills in

| Field | Value |
|---|---|
| auto, defaulted or non-editable (`id`, `created_at`, `created_by`, `deleted_at`) | left to the model |
| `choices` | cycles through the choice values |
| `CharField` / `SlugField` / `TextField` | `"<field>-<n>"`, unique, within `max_length` |
| `EmailField` / `URLField` / `GenericIPAddressField` | `user<n>@example.com` / `https://example.com/<n>` / `10.x.y.z` |
| integer / float / decimal | a sequence inside the type's range, the field's `Min`/`MaxValueValidator`s and `max_digits` |
| date / datetime / time / duration | today / now / now / `n` minutes |
| UUID / JSON / binary / file / image | `uuid4()` / `{"n": n}` / `b""` / a small file |
| `null=True, blank=True` (non-relation) | `None` (`null=True` alone: a value) |
| `ForeignKey` / `OneToOneField` | a new row from the target's factory. A nullable FK stays `None` on a cycle or deeper than `FactoryBuilder.max_depth` (3) |
| `ManyToManyField` | empty. `create(Event, tags=[t1, t2])` sets rows, `create(Event, tags=3)` creates three |
| the user model's `password` | `karni.testing.factories.DEFAULT_PASSWORD`, hashed, so tests can log in |
| any other required field | an error **when used**, naming the fix (pass the field, or write an explicit factory) |

Unique fields get sequence-based values, and unique constraints over FKs hold
because every related row is new. Constraints over choices or booleans alone,
and required relation cycles (`Loop.partner = FK("self")`, not nullable), need
an explicit factory or an override. The error says which.

Nested overrides use factory-boy's syntax: `create(Novel,
writer__publisher=acme)`, `create(Event, tags=[t], tags__through_defaults={...})`.

### Escape hatches

- Keyword overrides on every call.
- An explicit factory in `<app>/factories.py`.
- `auto_factory(model, builder=MyBuilder())` with a `FactoryBuilder` subclass.
  Every rule is an overridable method (`declaration`, `relation_value`,
  `choice_value`, `text_value`, `number_value`, `decimal_value`, `value`,
  `image_value`), and `max_depth` is a class attribute.

Public API: `factory_for`, `auto_factory`, `explicit_factories`, `create`,
`create_batch`, `build`, `clear_cache`, `FactoryBuilder`, `AutoFactory`
(base of generated factories), `AutoSubFactory`, `DEFAULT_PASSWORD`.

## The cache in tests

The `karni` pytest plugin runs every test on an empty local-memory cache:
each alias in `CACHES` becomes a `LocMemCache` of its own (with the alias's
`KEY_PREFIX`, `VERSION`, `KEY_FUNCTION` and `TIMEOUT`), cleared before and
after the test. Nothing a test caches reaches the next test, a later run or
the development server that shares `REDIS_URL`: rate-limit counters, a
listener's "already queued" flag, a cached page or menu. The tests of a new
project never connect to Redis. A `DummyCache` alias stays as it is.

A test that needs the project's own cache (one that checks Redis itself)
says so:

```python
import pytest


@pytest.mark.karni_project_cache
def test_the_lock_is_shared_between_workers():
    ...
```

`karni_test_cache = project` in the pytest ini file (`[tool.pytest.ini_options]`
in `pyproject.toml`) keeps the project's cache for every test, the rule
before 0.5.0. A fixture named `_karni_test_cache` in `conftest.py` replaces
the plugin's. Code that keeps a cache object from import time
(`caches["default"]` stored in a module) keeps that object: use
`django.core.cache.cache` or look the alias up when it is needed.

## Rate limits in tests

The `karni` pytest plugin gives DRF's throttles an empty cache of their own
at the start of every test. A suite that posts to a public form many times
(each public `create` is limited to `KARNI_PUBLIC_CREATE_RATE`, 10 an hour
by default), or logs in again and again, never runs out of requests because
of an earlier test, and a run never inherits counters an earlier run left
in Redis. Inside one test the limits still work, so a test can prove one:

```python
def test_the_contact_form_is_rate_limited(client_as, settings):
    settings.KARNI_PUBLIC_CREATE_RATE = "2/hour"
    anonymous = client_as(None)
    enquiry = {"name": "Ada", "message": "Do you design schools?"}
    for _ in range(2):
        assert anonymous.post("/api/enquiries/", enquiry).status_code == 201
    assert anonymous.post("/api/enquiries/", enquiry).status_code == 429
```

`assert_crud` and `assert_isolated` switch throttling off for the resource
they test. The throttles' cache stays fresh with `karni_project_cache` too.
To keep the shared cache for throttles as well, define an autouse fixture
named `_karni_fresh_throttles` in `conftest.py` that does nothing.

## Queued listeners and Celery tasks

A `queued=True` listener (or any task) dispatches on commit and runs in a
worker, so a test sees nothing unless it runs Celery in-process and executes
the commit callbacks. pytest-django's `settings` fixture and
`django_capture_on_commit_callbacks` do both:

```python
@pytest.fixture(autouse=True)
def _in_process_celery(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


def test_a_confirmed_booking_is_emailed(client_as, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client_as("attendee").post(...)      # the save that queues the listener
    assert len(mail.outbox) == 1
```

The listener function itself is unchanged by the decorator, so unit tests can
also call it directly with a model instance.

## Query budgets and N+1 (`karni.testing.performance`)

Three layers, all active in every test run with no project code:

### 1. Endpoint budgets raise in tests

The `karni` pytest plugin sets `KARNI_QUERY_BUDGET_MODE = "raise"` for the
session, so any test request that pushes a `BaseViewSet` action over its
budget (list/retrieve 8, create/update 12, destroy 10, other 15, described in
[api](api.md#query-budgets)) fails with the grouped report:

```
karni.performance.QueryBudgetExceeded: EventViewSet.list ran 14 queries against a budget of 8.
14 queries, 12 duplicated, 3.1 ms in SQL
  12× SELECT … FROM "app_tag" INNER JOIN … WHERE … = %s
      ← EventSerializer.tag_names (app/serializers.py:41 in get_tag_names)
Fix the repeated query (…), or declare query_budget = Budget(list=N, reason=...).
```

The fix is in the code (a hint, a serializer change). Raising the budget is
a declaration on the viewset: `query_budget = Budget(list=20, reason="...")`.
To find the fix, run [`karni queries EventViewSet.list --as <user>`](debugging/queries.md)
(or pipe the failure into [`karni explain -`](debugging/explain.md), which
prints that command): it names the field and relation behind each repeated
statement and the hint that removes it.

| To change it | Do |
|---|---|
| one test | `with override_settings(KARNI_QUERY_BUDGET_MODE="off"): ...` |
| one run | `pytest --karni-query-budget=warn` (or `off`) |
| the project | `karni_query_budget_mode = warn` in the pytest ini section |
| drop the plugin | `pytest -p no:karni` |

### 2. The `query_budget` fixture

An explicit maximum around any block, such as a non-viewset view, a service
or a task:

```python
def test_dashboard(client, query_budget):
    with query_budget(5):
        client.get("/dashboard/")

def test_report_service(query_budget):
    with query_budget(3, label="weekly report") as recorder:
        build_weekly_report()
    assert recorder.count == 3
```

The same context manager is importable as `karni.testing.query_budget(n,
*, label="block", using=None)`. It yields the recorder and raises
`QueryBudgetExceeded` (an `AssertionError`) with the grouped report.

### 3. The scaling check

A budget cannot see an N+1 in a test with one row. The scaling check can: for
every routed project `BaseViewSet` it measures

- `list` with **2** rows and with **12** rows,
- `retrieve` of a row with **2** related rows per to-many relation the
  serializer renders, and of one with **12**,

and fails if the query count grows. Rows come from the automatic factories
(explicit ones win). Related rows are seeded along the serializer's own
nested relations, three levels deep, so an N+1 at any level shows. The
requester is created per case, holds every role the `read` predicate names
(`HasRole`), and owns the rows its `Owned` paths name. Budgets and the
response cache are off while measuring.

It ships inside the architecture suite every project already runs, so no
wiring is needed:

```bash
pytest --pyargs karni.testing.architecture   # rules + the scaling check
pytest --pyargs karni.testing.performance    # the scaling check alone
```

A failure reads:

```
EventViewSet.list: 3 queries with 2 rows, 13 with 12: the query count grows with the data (N+1).
13 queries, 10 duplicated, 1.2 ms in SQL
  10× SELECT … FROM "app_tag" … WHERE "app_event_tags"."event_id" = %s
      ← EventSerializer.tag_names
```

Outcomes other than pass/fail are explicit:

- **Skipped, with the reason**, when the generated requester cannot see the
  seeded rows (a `Where(...)` rule, a traversal `Owned` path) or the endpoint
  does not answer 200. Give the model an explicit factory that produces
  readable rows.
- **Opted out** with the class marker, reason required (a reason-less marker
  fails the case):

  ```python
  # karni: allow(query-scaling): one signed S3 URL per row, bounded by the page
  class AttachmentViewSet(BaseViewSet):
      ...
  ```

The pieces are public for project tests: `scaling_cases()` (the
`ScalingCase`s found), `check_scaling(case) -> ScalingResult` (`small`,
`large`, `grows`, `skipped`, `message()`), and the constants
`SCALING_SMALL = 2`, `SCALING_LARGE = 12`.

```python
from karni.testing.performance import ScalingCase, check_scaling

def test_my_endpoint_is_flat(db):
    result = check_scaling(ScalingCase(ReportViewSet, "list"))
    assert not result.grows, result.message()
```

Under the hood all three layers share `karni.performance.record_queries()`,
the recorder that also feeds the dev query log
([api](api.md#query-budgets)).

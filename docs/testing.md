---
description: Karni's test tooling: the assert_crud and assert_isolated one-liners, the pytest plugin, query budgets, the scaling check and the architecture rules suite.
---

# Testing

Karni ships the test tooling a project would otherwise write by hand, and
wires it in so that it runs without project code:

| Piece | What it gives you |
|---|---|
| [`APITestCase`, `client_as`](#clients-per-role) | an authenticated client per role, in one call |
| [`assert_crud`](#the-full-crud-surface-in-one-call) | the whole CRUD surface of a resource for a role, checked against its `access` declaration and the OpenAPI contract |
| [`assert_isolated`](#isolation-the-test-people-forget) | one line proving a role cannot see or touch another owner's rows |
| [`assert_schema_snapshot`](#schema-snapshot) | an accidental API break fails CI |
| [`karni.testing.factories`](#automatic-factories-karnitestingfactories) | a valid factory-boy factory for any model, with realistic values; `<app>/factories.py` overrides |
| [`karni.testing.performance`](#query-budgets-and-n1-karnitestingperformance) | the `query_budget` fixture, per-endpoint budgets that raise, the N+1 scaling check |
| the `karni` pytest plugin | loaded automatically (`pytest11` entry point) wherever `karni` is installed |
| [`karni.testing.architecture`](enforcement.md) | the build-failing architecture rules (and the scaling check) |

CI runs two invocations: the project's own suite (`pytest`) and Karni's rules
(`pytest --pyargs karni.testing.architecture`). Both need `pytest-django`
and a test database. `karni make test <Model>` writes a starting test file
like the one below.

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

## Isolation: the test people forget

```python
self.assert_isolated(EventViewSet, "organizer")
```

Two users with the role each get a row of their own. The first must see
their own row (the positive control) and must not reach the other's through
any surface: the list; retrieve, update and delete (404, never a 403 that
confirms the row exists, and the row stays unchanged); a nested `?expand=`
from another resource that points at it; a filter, `?search=` or
`?ordering=` parameter; the admin (the changelist, its search, the change
form and a POST to it — for the `grant` dimension, since the admin's rows
follow the roles' grants); an export route, when the resource has one; and
a create body naming another owner, which is
ignored and stamped with the requester. It runs for every isolation
dimension that applies: `owner` (any `Owned(...)` read path) and `grant`
(a `Granted()` or `Can` read where the role's grant for the model's `view`
permission is `own` or `related:<key>`; the users get distinct related
values) ship with Karni. A tenancy module adds `tenant` by registering a
dimension, and existing tests then cover it with no change. A resource no
dimension applies to fails and says why: `read=Authenticated()`, or a role
whose grant is `all`, lets every signed-in user see every row, which is
exactly the bug this catches. Probes that cannot run for a resource (no
admin registration, no export route) are listed in the report's `notes`.

## Schema snapshot

```python
# tests/test_api_schema.py
from karni.testing import assert_schema_snapshot

def test_the_api_contract_is_unchanged(db):
    assert_schema_snapshot()
```

The generated schema is compared with `tests/openapi.snapshot.json`. A
difference fails, listing breaking changes (removed and changed paths) first.
A missing snapshot is written and the test passes, except under CI, where it
fails, because a snapshot that was never committed protects nothing. To
accept an intended change, run `KARNI_UPDATE_SNAPSHOTS=1 karni test`, then
commit the file.

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
   wins, else the first defined. Explicit factories are used everywhere — by
   `create()`, as the related-object factory inside generated ones, and by
   the scaling check.
2. a **generated** one (`auto_factory(model)`, cached per model).

```python
# myapp/factories.py — picked up automatically
import factory
from factory.django import DjangoModelFactory

from myapp.models import Venue


class VenueFactory(DjangoModelFactory):
    class Meta:
        model = Venue

    name = factory.Faker("company")
    city = "Pune"
```

Discovery runs once per process; call `karni.testing.factories.clear_cache()`
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
| `ForeignKey` / `OneToOneField` | a new row from the target's factory; a nullable FK stays `None` on a cycle or deeper than `FactoryBuilder.max_depth` (3) |
| `ManyToManyField` | empty; `create(Event, tags=[t1, t2])` sets rows, `create(Event, tags=3)` creates three |
| the user model's `password` | `karni.testing.factories.DEFAULT_PASSWORD`, hashed — tests can log in |
| any other required field | an error **when used**, naming the fix (pass the field, or write an explicit factory) |

Unique fields get sequence-based values, and unique constraints over FKs hold
because every related row is new. Constraints over choices or booleans alone,
and required relation cycles (`Loop.partner = FK("self")`, not nullable), need
an explicit factory or an override — the error says which.

Nested overrides use factory-boy's syntax: `create(Novel,
writer__publisher=acme)`, `create(Event, tags=[t], tags__through_defaults={...})`.

### Escape hatches

- keyword overrides on every call;
- an explicit factory in `<app>/factories.py`;
- `auto_factory(model, builder=MyBuilder())` with a `FactoryBuilder` subclass
  — every rule is an overridable method (`declaration`, `relation_value`,
  `choice_value`, `text_value`, `number_value`, `decimal_value`, `value`,
  `image_value`) and `max_depth` is a class attribute.

Public API: `factory_for`, `auto_factory`, `explicit_factories`, `create`,
`create_batch`, `build`, `clear_cache`, `FactoryBuilder`, `AutoFactory`
(base of generated factories), `AutoSubFactory`, `DEFAULT_PASSWORD`.

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
budget (list/retrieve 8, create/update 12, destroy 10, other 15 — see
[api](api.md#query-budgets)) fails with the grouped report:

```
karni.performance.QueryBudgetExceeded: EventViewSet.list ran 14 queries; budget is 8.
14 queries, 12 duplicated, 3.1 ms in SQL
  12× SELECT … FROM "app_tag" INNER JOIN … WHERE … = %s
      ← EventSerializer.tag_names (app/serializers.py:41 in get_tag_names)
Fix the repeated query (…), or declare query_budget = Budget(list=N, reason=...).
```

The fix is in the code (a hint, a serializer change); raising the budget is
a declaration on the viewset: `query_budget = Budget(list=20, reason="...")`.

| To change it | Do |
|---|---|
| one test | `with override_settings(KARNI_QUERY_BUDGET_MODE="off"): ...` |
| one run | `pytest --karni-query-budget=warn` (or `off`) |
| the project | `karni_query_budget_mode = warn` in the pytest ini section |
| drop the plugin | `pytest -p no:karni` |

### 2. The `query_budget` fixture

An explicit maximum around any block — a non-viewset view, a service, a
task:

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
*, label="block", using=None)`; it yields the recorder and raises
`QueryBudgetExceeded` (an `AssertionError`) with the grouped report.

### 3. The scaling check

A budget cannot see an N+1 in a test with one row. The scaling check can: for
every routed project `BaseViewSet` it measures

- `list` with **2** rows and with **12** rows,
- `retrieve` of a row with **2** related rows per to-many relation the
  serializer renders, and of one with **12**,

and fails if the query count grows. Rows come from the automatic factories
(explicit ones win); related rows are seeded along the serializer's own
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
EventViewSet.list: 3 queries with 2 rows, 13 with 12 — the query count grows with the data (N+1).
13 queries, 10 duplicated, 1.2 ms in SQL
  10× SELECT … FROM "app_tag" … WHERE "app_event_tags"."event_id" = %s
      ← EventSerializer.tag_names
```

Outcomes other than pass/fail are explicit:

- **Skipped, with the reason**, when the generated requester cannot see the
  seeded rows (a `Where(...)` rule, a traversal `Owned` path) or the endpoint
  does not answer 200 — give the model an explicit factory that produces
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

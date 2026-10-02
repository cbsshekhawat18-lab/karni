# Testing

Karni ships the test tooling a project would otherwise write by hand, and
wires it in so that it runs without project code:

| Piece | What it gives you |
|---|---|
| [`karni.testing.factories`](#automatic-factories-karnitestingfactories) | a valid factory-boy factory for any model; `<app>/factories.py` overrides |
| [`karni.testing.performance`](#query-budgets-and-n1-karnitestingperformance) | the `query_budget` fixture, per-endpoint budgets that raise, the N+1 scaling check |
| the `karni` pytest plugin | loaded automatically (`pytest11` entry point) wherever `karni` is installed |
| [`karni.testing.architecture`](enforcement.md) | the build-failing architecture rules (and the scaling check) |

CI runs two invocations: the project's own suite (`pytest`) and Karni's rules
(`pytest --pyargs karni.testing.architecture`). Both need `pytest-django`
and a test database.

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

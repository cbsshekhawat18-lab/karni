---
description: "Why Karni enforces permissions at the queryset rather than the view: one row filter that list, detail, relation fields and expansion all share."
---

# Permissions at the queryset

Most permission systems answer one question — *may this request reach this
view?* — and leave the second, *which rows?*, to whoever writes
`get_queryset()`. The leak everyone eventually ships is a `retrieve` that
forgot to filter, a relation field that accepts any primary key, or an
`?expand=` that embeds a row the requester could never list. Karni compiles
one declaration into both answers, so they cannot disagree.

## One declaration, two layers

```python
class BookingViewSet(BaseViewSet):
    model = Booking
    access = Access(
        read=Owned("attendee") | Owned("event__organizer") | HasRole("staff"),
        write=Owned("attendee"),
        create=Authenticated(),
    )
```

Every predicate has a request-level answer and a row-level answer:

| Predicate | Gate (may the request proceed?) | Rows |
|---|---|---|
| `Public()` | everyone | all |
| `Authenticated()` | signed-in users | all |
| `HasRole("staff")` | holders of the group | all for holders, none otherwise |
| `Owned("attendee")` | signed-in users | `attendee = request.user` |
| `Owned("event__organizer")` | signed-in users | the relation path ends at the user |
| `Where(fn)` | `fn(request)` as a bool, or passes | the `Q` `fn(request)` returns |
| `a \| b`, `a & b` | any / all | OR / AND of the row filters |

The **gate** runs first, as a DRF permission, before any query. The **row
filter** is applied in `get_queryset()`, and it is authoritative: lists,
details, custom actions, relation-field validation and `?expand=` all go
through it. A row outside `read` does not exist for that request — a 404
with no existence oracle — and a readable row outside `write` is a 403.

## Why the queryset, not the object

Object-level permission checks (`has_object_permission`) run *after* the row
was fetched, one object at a time. They cannot filter a list, they cannot
scope a relation field's choices, and they are easy to skip in a custom
action. A queryset filter is applied once, before anything is fetched, and
every code path that asks for rows inherits it:

- **Lists and details** share one filter, so a row you cannot list you
  cannot fetch by id either.
- **Relation fields** (`booking.event`) accept only primary keys of rows the
  requester can read through the *target* model's viewset. An out-of-scope
  id fails exactly like a missing one.
- **Expansion** embeds only readable rows; a to-one target outside the scope
  renders as `null`.
- **Owner stamping**: a direct foreign key to the user named by `Owned` in
  `write` or `create` is set from `request.user` on create and is read-only
  in the serializer. The body never chooses the owner.

## Model scopes sit underneath

The row filter is only ever `filter()`-ed onto the model's default manager,
and the default manager runs the [scope pipeline](../models.md#scopes-the-filters-every-default-manager-applies):
`soft_delete` today, `tenant` when the tenancy module is installed. No
predicate, `HasRole` bypasses included, can reach a soft-deleted row or
another tenant's row. Lifting a scope is a separate, logged, reasoned call:
`Model.objects.without("soft_delete", reason="restore screen")`.

## Testing it in two lines

```python
class BookingAPITests(APITestCase):
    def test_crud(self):
        self.assert_crud(BookingViewSet, "attendee")      # every promised allow and deny

    def test_isolation(self):
        self.assert_isolated(BookingViewSet, "attendee")  # another owner's rows: unreachable
```

`assert_crud` derives the expected status of every action from the
declaration and checks the API against it, including the 404-not-403 rule;
`assert_isolated` creates rows for two owners and proves one cannot see,
change or reference the other's.

## Escape hatches, least to most drastic

1. Change the declaration.
2. `Where(...)` for arbitrary row logic; `@action(access=...)` for one
   action; `get_access()` to compute the declaration per request.
3. Override `filter_queryset_for_user(queryset)` — it receives the scoped
   queryset — with a `# karni: allow(access-override): <reason>` marker.
4. `access = Unscoped(reason="...")`: plain DRF permissions, rows limited
   only by model scopes. The reason is published in the schema.

Everything in between is a declaration you can read in one place, and that
`karni context` prints for every viewset.

# Friction log: rebuilding Social Stats' leads module on Karni

Every place the rebuild needed project code that Karni should arguably have
provided, in the order it was hit. Entries 1, 2, 3 and 14 carry a **Status**:
the three high-severity ones were fixed in Karni the same day. Each entry says what was wanted, what was
done instead, and what it cost. The rule for the rebuild was Karni's
documented public surface only: no edits to Karni, no undocumented imports.
Karni 0.2.0 (commit `8333c9c`), Python 3.12, SQLite.

Severity: **high** is a correctness or security trap, **medium** is real
project code an agent writes every time, and **low** is cosmetic or one-off.

## 1. Membership tenancy has no scope (medium, documented)

**Wanted:** "a member sees the rows of the workspaces they belong to". Social
Stats' rule (`TenantScopedMixin`) is exactly that, through agency and staff
assignments. Karni's scopes are `all`, `own`, `related:<key>` and `custom:`.
The `related:<key>` scope compares a row's path with *one* value, `user.<key>`, so it
cannot express membership through a many-to-many.

**Did:** registered `custom:workspace` with `register_scope` (`crm/scopes.py`
and `crm/apps.py`, 13 lines).

**Karni could:** ship a membership scope (`member:<scope path>` following
`Karni.scope_paths` through a many-to-many), or the tenancy module the testing
docs anticipate.

**Status: it could already, and now says so.** `own` takes an owner *path*,
and a path through the membership many-to-many is exactly this rule:
`owner_field = "workspace__members"`. Nothing documented it. The roles docs
now have a "Membership" section, and this example uses it (the custom scope
is gone).

## 2. A custom scope must name every model's path (high, fixed)

**Wanted:** the scope to find each model's way to its workspace on its own.

**Did:** one branch per model in `workspace_rows` (`Workspace` → `members`,
`LeadActivity` → `lead__workspace__members`, the rest → `workspace__members`).

**What went wrong:** adding one more model (`FollowUp`, see the case study)
made `GET /api/follow-ups/` answer **500** for every member until the scope
learned its path, and the generated test stayed green (entry 3). Nothing in
`karni check` noticed.

**Karni could:** resolve a custom scope's path from `Karni.scope_paths`, and
fail `karni check` when a model granted by a custom scope has no resolvable
path.

**Status: fixed.** Every path a role's grants filter on (`own` owner paths,
`related:` scope paths, and whatever a `custom:` scope builds) is resolved
at boot on each model the grant covers. One that does not resolve fails
`karni check` with `E214` instead of answering 500.

## 3. Generated tests cannot cover a custom scope, and drop isolation silently (high, fixed)

**Wanted:** `karni make model … --with test` to keep giving the two
one-liners (`assert_crud`, `assert_isolated`) that the docs promise.

**What happened:**

- Generated before the roles were declared, the tests named the default role
  `user`. Retargeted to `member`, `assert_crud` failed: its generated
  requester belongs to no workspace, so the list missed its own row, the
  create answered 400 (`Invalid pk … object does not exist` for the
  workspace) and pagination returned no rows.
- `assert_isolated` refused: "nothing isolates rows … role 'member' holds no
  'own' or 'related:<key>' grant".
- For the next model the generator chose role `staff` and **left the
  isolation test out without saying so**. That test passes while members hit
  the 500 from entry 2.

**Did:** deleted the four generated tests and wrote `crm/tests/test_leads.py`
by hand: two workspaces, two members, every surface checked (list, retrieve,
update, custom actions, search, export, create into another workspace),
plus the pipeline actions. That came to 128 lines.

**Karni could:** let a scope register an isolation dimension with a fixture
hook, which `assert_isolated` and `karni make test` then use. It should also never
drop the isolation test silently: it could generate a failing placeholder or
print a warning naming the reason.

**Status: fixed.** With membership as `own` and an owner path,
`assert_crud` and `assert_isolated` drive it. They had failed only because the
test factories passed a single user to the many-to-many (fixed). `karni make
test` now says, in its output and in the test file, why it leaves
`assert_isolated` out: a custom scope, or no role partitioning the rows.
This example's tests are now the four generated ones plus the cases they do
not reach.

## 4. The field DSL has no defaults and no list JSON (low)

**Wanted:** `quality_score:int=50`, `source_channel:str:50=whatsapp`,
`tags:json[]`.

**Did:** hand-edited five field lines after generating. The `tags:json` field had been
generated with `default=dict` where the original holds a list.

**Karni could:** accept `=default` in the DSL and a list form for JSON fields.

## 5. No reverse name in the DSL, so no `?expand=activities` (low)

**Did:** added `related_name="activities"` by hand and an
`expandable_fields` mapping on the viewset (6 lines).

## 6. Filtering a JSON list by one member, `?tag=` (medium)

**Wanted:** the original's `?tag=hot`. Derived filters skip JSON fields, and
`tags__contains=[…]` is unsupported on SQLite.

**Did:** a `get_queryset` override with a database-vendor branch (8 lines).

**Karni could:** derive a portable `<json>__has` filter for list-shaped JSON
fields.

## 7. State changes with a written timeline (medium, partly domain code)

**Wanted:** status, assignment and conversion each recorded with who, when
and a note, like the original's `LeadActivity` timeline.

**Did:** `crm/services.py` (66 lines) and seven `@action`s. Karni's change
history (`Karni.audit = True`, one line) already records every field change
with its author. What it cannot hold is a free-text note or a logged call.

**Karni could:** let a project attach a note to an entity's history entry
(an annotation on `karni.audit`), which would leave `LeadActivity` for calls
and messages only.

## 8. Endpoint parity breaks existing clients (medium)

| Original | Rebuild (Karni) |
|---|---|
| `GET /api/leads/export.csv/` | `GET /api/leads/export/?format=csv` (and `xlsx`) |
| `POST /api/leads/import_csv/`, one step | `/api/leads/import/`: upload, mandatory preview, commit |
| `?q=`, `?min_score=`, `?from=`, `?to=` | `?search=`, `?quality_score__gte=`, `?created_at__gte=`, `?created_at__lte=` |

**Did:** kept Karni's names, so a client written for Social Stats must change.
Unknown query parameters are ignored, so an old `?q=` returns the whole list
instead of failing.

**Karni could:** accept filter aliases on a viewset, or answer 400 on an
unknown filter parameter in development.

## 9. UUID primary keys inside JSON (low)

**What happened:** storing user ids in an activity's `metadata` raised
`TypeError: Object of type UUID is not JSON serializable`, and the original's
`int(user_id)` parsing broke on UUIDs.

**Did:** `str()` around two ids and a plain `.get(pk=…)` lookup.

**Karni could:** give `BaseModel` JSON fields an encoder that handles UUIDs.

## 10. No documented way to refresh after a custom action in the UI (medium)

**Wanted:** after `POST /leads/<id>/status/`, the table, the board and the
detail to show the new status.

**Did:** `refetch()` where the page owns the query, and a React `key` bump to
remount `ResourceTable`/`ResourceDetail` where it does not. `karniKeys` is
exported from `@karni/ui` but not in [the UI reference](../../docs/ui.md), so
it was off limits.

**Karni could:** a `useResourceAction(resource, action)` hook that posts and
invalidates the resource, plus documentation for `karniKeys`.

## 11. No board (kanban) component (medium)

**Did:** `LeadKanban.tsx`, 66 lines with HTML5 drag and drop, on
`useResourceList`.

**Karni could:** a `ResourceBoard` grouped by an enum field. It is a candidate
under the three-occurrences rule, not yet a decision.

## 12. `ResourceTable` cannot be told "only these columns" (low)

**Did:** `columnsOverride` with a list of the 18 fields the original's
table did not show.

**Karni could:** a `visibleColumns` prop.

## 13. A foreign key to the user model renders as "[object Object]" (medium)

**What happened:** `assigned_to` expanded to a user object. The schema
carries no `x-karni-relation` for the user model (users are not an API
resource), so `ResourceDetail` printed the object as a string.

**Did:** a `render` override on the detail page and a cell on the table
(`components/assignee.tsx`, 9 lines).

**Karni could:** emit relation metadata for the user model and render any
expanded object through `displayLabel`.

## 14. Python 3.14 installs, then the admin crashes (high, fixed)

**What happened:** `python3 -m venv` picked Python 3.14 on this machine.
Karni (`requires-python >= 3.12`) and Django 5.1.15 installed cleanly, every
API test passed, and every admin page answered **500**
(`AttributeError: 'super' object has no attribute 'dicts'`, Django 5.1 on
Python 3.14).

**Did:** rebuilt the venv on Python 3.12.

**Karni could:** cap `requires-python` below 3.14 while it targets Django
5.1, or move to Django 5.2 LTS, which the security scan asks for anyway
(pip-audit reports ten advisories against Django 5.1.15 with no 5.1 fix).

**Status: fixed.** Karni requires Django 5.2 LTS (`>=5.2.8`, the first
release supporting Python 3.14) and django-unfold 0.110. CI runs Python
3.12, 3.13 and 3.14. This example's admin answers 200 on Python 3.14.4, and
pip-audit finds nothing.

## What Karni caught that the rebuild got wrong

- `karni check` failed the build on a `Lead.objects.filter(...).update(...)`
  in a test: the bulk update bypasses the change history `Lead` keeps.
- The row scope reached the custom actions, the export, the import and the
  admin with no code: a member's `POST /leads/<other workspace's lead>/convert/`
  is a 404, and their CSV export omits the other workspace's rows.

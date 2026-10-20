# Friction log — rebuilding Social Stats' leads module on Karni

Every place the rebuild needed project code that Karni should arguably have
provided, in the order it was hit. Each entry says what was wanted, what was
done instead, and what it cost. The rule for the rebuild was Karni's
documented public surface only: no edits to Karni, no undocumented imports.
Karni 0.2.0 (commit `8333c9c`), Python 3.12, SQLite.

Severity: **high** = a correctness or security trap; **medium** = real
project code an agent writes every time; **low** = cosmetic or one-off.

## 1. Membership tenancy has no scope — medium

**Wanted:** "a member sees the rows of the workspaces they belong to". Social
Stats' rule (`TenantScopedMixin`) is exactly that, through agency and staff
assignments. Karni's scopes are `all`, `own`, `related:<key>` and `custom:`;
`related:<key>` compares a row's path with *one* value, `user.<key>`, so it
cannot express membership through a many-to-many.

**Did:** registered `custom:workspace` with `register_scope` (`crm/scopes.py`
and `crm/apps.py`, 13 lines).

**Karni could:** ship a membership scope (`member:<scope path>` following
`Karni.scope_paths` through a many-to-many), or the tenancy module the testing
docs anticipate.

## 2. A custom scope must name every model's path — high

**Wanted:** the scope to find each model's way to its workspace on its own.

**Did:** one branch per model in `workspace_rows` (`Workspace` → `members`,
`LeadActivity` → `lead__workspace__members`, the rest → `workspace__members`).

**What went wrong:** adding one more model (`FollowUp`, see the case study)
made `GET /api/follow-ups/` answer **500** for every member until the scope
learned its path — and the generated test stayed green (entry 3). Nothing in
`karni check` noticed.

**Karni could:** resolve a custom scope's path from `Karni.scope_paths`, and
fail `karni check` when a model granted by a custom scope has no resolvable
path.

## 3. Generated tests cannot cover a custom scope, and drop isolation silently — high

**Wanted:** `karni make model … --with test` to keep giving the two
one-liners (`assert_crud`, `assert_isolated`) that the docs promise.

**What happened:**

- generated before the roles were declared, the tests named the default role
  `user`; retargeted to `member`, `assert_crud` failed — its generated
  requester belongs to no workspace, so the list missed its own row, the
  create answered 400 (`Invalid pk … object does not exist` for the
  workspace) and pagination returned no rows;
- `assert_isolated` refused: "nothing isolates rows … role 'member' holds no
  'own' or 'related:<key>' grant";
- for the next model the generator chose role `staff` and **left the
  isolation test out without saying so**. That test passes while members hit
  the 500 from entry 2.

**Did:** deleted the four generated tests and wrote `crm/tests/test_leads.py`
by hand: two workspaces, two members, every surface checked (list, retrieve,
update, custom actions, search, export, create into another workspace),
plus the pipeline actions — 128 lines.

**Karni could:** let a scope register an isolation dimension with a fixture
hook, which `assert_isolated` and `karni make test` then use; and never drop
the isolation test silently — generate a failing placeholder or print a
warning naming the reason.

## 4. The field DSL has no defaults and no list JSON — low

**Wanted:** `quality_score:int=50`, `source_channel:str:50=whatsapp`,
`tags:json[]`.

**Did:** hand-edited five field lines after generating; `tags:json` had been
generated with `default=dict` where the original holds a list.

**Karni could:** accept `=default` in the DSL and a list form for JSON fields.

## 5. No reverse name in the DSL, so no `?expand=activities` — low

**Did:** added `related_name="activities"` by hand and an
`expandable_fields` mapping on the viewset (6 lines).

## 6. Filtering a JSON list by one member (`?tag=`) — medium

**Wanted:** the original's `?tag=hot`. Derived filters skip JSON fields, and
`tags__contains=[…]` is unsupported on SQLite.

**Did:** a `get_queryset` override with a database-vendor branch (8 lines).

**Karni could:** derive a portable `<json>__has` filter for list-shaped JSON
fields.

## 7. State changes with a written timeline — medium (partly domain code)

**Wanted:** status, assignment and conversion each recorded with who, when
and a note, like the original's `LeadActivity` timeline.

**Did:** `crm/services.py` (66 lines) and seven `@action`s. Karni's change
history (`Karni.audit = True`, one line) already records every field change
with its author; what it cannot hold is a free-text note or a logged call.

**Karni could:** let a project attach a note to an entity's history entry
(an annotation on `karni.audit`), which would leave `LeadActivity` for calls
and messages only.

## 8. Endpoint parity breaks existing clients — medium

| Original | Rebuild (Karni) |
|---|---|
| `GET /api/leads/export.csv/` | `GET /api/leads/export/?format=csv` (and `xlsx`) |
| `POST /api/leads/import_csv/`, one step | `/api/leads/import/`: upload, mandatory preview, commit |
| `?q=`, `?min_score=`, `?from=`, `?to=` | `?search=`, `?quality_score__gte=`, `?created_at__gte=`, `?created_at__lte=` |

**Did:** kept Karni's names; a client written for Social Stats must change.
Unknown query parameters are ignored, so an old `?q=` returns the whole list
instead of failing.

**Karni could:** accept filter aliases on a viewset, or answer 400 on an
unknown filter parameter in development.

## 9. UUID primary keys inside JSON — low

**What happened:** storing user ids in an activity's `metadata` raised
`TypeError: Object of type UUID is not JSON serializable`, and the original's
`int(user_id)` parsing broke on UUIDs.

**Did:** `str()` around two ids and a plain `.get(pk=…)` lookup.

**Karni could:** give `BaseModel` JSON fields an encoder that handles UUIDs.

## 10. No documented way to refresh after a custom action in the UI — medium

**Wanted:** after `POST /leads/<id>/status/`, the table, the board and the
detail to show the new status.

**Did:** `refetch()` where the page owns the query, and a React `key` bump to
remount `ResourceTable`/`ResourceDetail` where it does not. `karniKeys` is
exported from `@karni/ui` but not in [the UI reference](../../docs/ui.md), so
it was off limits.

**Karni could:** a `useResourceAction(resource, action)` hook that posts and
invalidates the resource; and document `karniKeys`.

## 11. No board (kanban) component — medium

**Did:** `LeadKanban.tsx`, 66 lines with HTML5 drag and drop, on
`useResourceList`.

**Karni could:** a `ResourceBoard` grouped by an enum field — a candidate
under the three-occurrences rule, not yet a decision.

## 12. `ResourceTable` cannot be told "only these columns" — low

**Did:** `columnsOverride` with a list of the 18 fields the original's
table did not show.

**Karni could:** a `visibleColumns` prop.

## 13. A foreign key to the user model renders as "[object Object]" — medium

**What happened:** `assigned_to` expanded to a user object; the schema
carries no `x-karni-relation` for the user model (users are not an API
resource), so `ResourceDetail` printed the object as a string.

**Did:** a `render` override on the detail page and a cell on the table
(`components/assignee.tsx`, 9 lines).

**Karni could:** emit relation metadata for the user model and render any
expanded object through `displayLabel`.

## 14. Python 3.14 installs, then the admin crashes — high

**What happened:** `python3 -m venv` picked Python 3.14 on this machine.
Karni (`requires-python >= 3.12`) and Django 5.1.15 installed cleanly, every
API test passed, and every admin page answered **500**
(`AttributeError: 'super' object has no attribute 'dicts'`, Django 5.1 on
Python 3.14).

**Did:** rebuilt the venv on Python 3.12.

**Karni could:** cap `requires-python` below 3.14 while it targets Django
5.1, or move to Django 5.2 LTS — which the security scan asks for anyway
(pip-audit reports ten advisories against Django 5.1.15 with no 5.1 fix).

## What Karni caught that the rebuild got wrong

- `karni check` failed the build on a `Lead.objects.filter(...).update(...)`
  in a test: the bulk update bypasses the change history `Lead` keeps.
- The row scope reached the custom actions, the export, the import and the
  admin with no code: a member's `POST /leads/<other workspace's lead>/convert/`
  is a 404, and their CSV export omits the other workspace's rows.

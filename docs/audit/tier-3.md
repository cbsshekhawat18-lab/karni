# Tier 3 — adversarial access audit

Repo `<REDACTED>`, branch `main`, commit `0873e51`.
Report only — no tracked file was modified. `git status` at the end shows only
new files under `docs/audit/` (plus the pre-existing untracked `.chronicle/`,
`.claude/worktrees/`, `.gitattributes`).

## Method

Scaffolded a real project with `karni new audit3` (KARNI_UI_SRC pointed at the
repo's `packages/karni-ui`), local Postgres 17 `karni_audit_t3`, Redis db 7,
the repo `.venv` (Python 3.12). `AUTH_USER_MODEL` swapped to `hr.User`
(a `branch` FK on the user) **before** the first migrate, exactly as
[docs/accounts.md](../accounts.md) prescribes. Models:

- `Branch`.
- `Employee(branch FK, salary Decimal, secret_note CharField, created_by via BaseModel)` with
  `class Karni: owner_field="created_by"; scope_paths={"branch": "branch"}; actions=["approve"]`
  and `class APIMeta: write_only=["secret_note"]` (the only field-hiding mechanism Karni has today).
- `Review(employee FK, rating, note)` with `scope_paths={"branch": "employee__branch"}`.
- `User(AbstractKarniUser)` with a `branch` FK so `related:branch` resolves.

`KARNI_ROLES`: `staff` (`*`→`all`), `manager` (employees/reviews `related:branch`,
plus `approve`), `clerk` (employees/reviews `own`, `add`→`all`), `payroll_blind`
(`hr.employee:view`→`all` — the role the brief asked for that "should not see
salary"; **no mechanism exists to express that**, so it sees the whole row).
Two viewsets on `Employee`: `EmployeeViewSet` (`access = Can(...)`, roles-as-data)
and `MyEmployeeViewSet` at `/api/my-employees/` (`Owned("created_by") | HasRole("staff")`,
the docs' Owned/HasRole pattern).

Users: `manager_a`(branch A, is_staff), `manager_b`(B), `clerk_a`(A), `clerk_b`(B),
`staff`, `payroll_blind` (=`blind`), `root` (superuser). Rows seeded in both
branches; one extra `Review` (`REV_X`) owned by `clerk_a` but pointing at a
branch-B employee (a deliberate cross-branch relation). JWT mode,
`KARNI_JWT_ACCESS_LIFETIME=1` minute.

Raw request/response logs: `docs/audit/evidence/tier-3/{scope,routes,privesc,admin,admin2,auth,auth2,search2}.{log,jsonl}`,
`schema-manager_a.json`, `verify-email.txt`.

---

## LEAKS

**No cross-branch row leak was found through any API route that exists.** Every
attempt by `manager_a` (branch A) and `clerk_a` (branch A) to reach branch-B
rows through list, retrieve, PATCH, PUT, DELETE, the `approve` action, nested
`?expand=`, `?branch=`/`?created_by=` filters, `?search=` and `?ordering=`
returned the other branch's data **not at all** (empty list) or **404** — never
the row. The row filter runs before filter/search/ordering, so none of those
parameters widens the scope.

Two real weaknesses were found. Neither is a cross-tenant row leak; both are
worth fixing.

**FAIL (admin, by design-gap — a real cross-branch data leak once a role is let into the admin).**
`karni.admin` applies **no row scoping** (ADR 0002 P2, admin half, is unbuilt).
A `manager_a` who is `is_staff` and whose `manager` group is given Django's
`view/change_employee` + `view_review` model permissions — the normal way to
let a role use the admin — sees and edits **every branch's** rows:

- `GET /admin/hr/employee/` → **200**, changelist count **9**, branch-B names
  "Bob Beta"/"Bianca Beta" present, branch-B salary `9000.00` shown.
- `GET /admin/hr/employee/<branch-B id>/change/` → **200**; the form shows
  salary `2000.00` **and the write-only `secret_note` value `B-SECRET-one`**.
- `POST .../change/` renaming Bob Beta → **302**; verified via the API as
  `manager_b`: the branch-B row now reads `"Bob Beta (edited by manager_a via admin)"`.
- `?q=needle` surfaces the branch-B secret row; `?branch__id__exact=<B>` lists 5
  branch-B rows; `/admin/autocomplete/?...term=Beta` returns both branch-B
  employee ids+names.

Implementing file: `karni/admin/base.py` / `karni/admin/soft_delete.py`
(`SoftDeleteAdminMixin.get_queryset` lifts only `soft_delete`; nothing applies
`access.read`). Evidence: `admin2.log`. This is exactly the gap ADR 0002 §2
("a staff user with admin access sees every row of every model") and §6 item 1
name. It is a **documented-but-unbuilt** control, so I rank it a FAIL of the
access model as a whole while recording it as the P2 gap it is: the moment any
non-superuser role is given admin model permissions, branch isolation is gone
in the admin, and the API's write-only field is fully readable there.

**PARTIAL — write-only fields are orderable; `?ordering=<write_only field>` is honoured.**
`BaseViewSet.ordering_fields = "__all__"` feeds DRF `OrderingFilter`, whose
`__all__` validates ordering against **model** fields, not serializer fields.
So a field the API never returns (`APIMeta.write_only`, and the user-model
sensitive fields) can still order the list, leaking the *relative order* of a
hidden column. Live proof (`scope.log` #26–#29, manager_a): default order
`[emp_a2, emp_a1]` (newest-first); `?ordering=secret_note` →
`[emp_a1, emp_a2]` (ascending by `A-SECRET-one` < `A-SECRET-two`);
`?ordering=-secret_note` → `[emp_a2, emp_a1]`. Confirmed against Karni's **own**
fixtures with a counter-test (see below): `?ordering=internal_note` reorders
`EventViewSet`'s list to ascending-by-`internal_note` even though the field is
`write_only`. The shipped test `tests/api/test_ordering.py::test_write_only_fields_are_not_orderable`
**passes only by coincidence** — its data (older="zzz", newer="aaa") makes
note-ascending equal to the default newest-first order, so the assertion holds
whether or not the field is orderable. This is a value-ordering oracle over a
hidden field (and, with the `payroll_blind`-style role that reads all rows, an
oracle over the whole table). It only reorders rows the caller may already read,
so it is **not** a cross-tenant row leak — hence PARTIAL. Same root cause makes
`?ordering=created_by__password`, `created_by__email`, `deleted_at` all accepted
(they execute SQL; they don't surface the value, but they are orderable).
Implementing file: `karni/api/viewsets.py:235` (`ordering_fields = "__all__"`).

The write-only field is **also a search_field** in this fixture, so
`?search=<secret value>` is likewise an oracle (membership/ranking) over the
hidden column for anyone who can read the row — `blind` search `A-SECRET-one`
returns the noted rows (`search2.log` #19–#24). This is a configuration choice
(don't put a write-only field in `search_fields`), but Karni does not warn about
it. For scoped roles it is harmless: search runs **after** the read filter, so
`manager_a`/`clerk_a` searching `needle` (a branch-B-only value) get `[]`.

---

## Results table

Status legend: PASS = no leak; PARTIAL; FAIL = leak; UNVERIFIED/N-A = feature
absent so nothing to leak. "impl" = implementing file. "test" = the shipped
test that claims the behaviour (or the probe id in the evidence logs).

### Row scope — `manager_a` / `clerk_a` vs branch B (EmployeeViewSet, `Can(...)`)

| Route / attempt | Verdict | impl | test | Observed (status + body excerpt) |
|---|---|---|---|---|
| list — does B appear? | PASS | `api/access.py` `AccessPermission`+`rows()`, `viewsets.py` `read_scope`; `accounts/roles.py` `rows_for` | `tests/api/test_access.py::test_list_is_row_scoped_and_roles_bypass`; `tests/testing/test_isolation.py` | 200; manager_a sees only `[emp_a2,emp_a1]` (count 2), clerk_a only `[emp_a1]` (count 1). B rows absent. (`scope.log` #1,#59) |
| retrieve B id | PASS | `viewsets.py::get_object` | `test_out_of_scope_retrieve_is_404_naming_the_scope` | 404 `{"detail":"No Employee matches the given query. Rows are limited by EmployeeViewSet.access read=Can('hr.employee:view')."}` (#3) |
| HEAD B id | PASS | same | — | 404 (#5) |
| PATCH B id | PASS | `get_object` via `write` | `test_unreadable_write_is_404...` | 404, same detail (#6) |
| PUT B id | PASS | same | — | 404 (#7) |
| DELETE B id | PASS | same | — | 404 (#8) |
| POST `approve/` B id | PARTIAL | `api/access.py` action override | `tests/accounts/test_roles.py` | manager_a: **404** (lookup via read scope, correct). clerk_a: **403** `{"detail":"...requires Can('hr.employee:approve')"}` — the request gate (no approve grant) fires before the row lookup, so an unreadable row answers 403 not 404 for a caller lacking the action grant. No data disclosed (no body, no existence confirmation beyond "you can't approve"), so not a leak; it is an inconsistency with the documented "unreadable → 404" rule. (#9,#67) |
| retrieve/PATCH B review | PASS/PARTIAL | same | — | manager_a 404; clerk_a PATCH 403 (has no `review:change` grant) — same gate-before-lookup nuance (#10,#11,#68,#69) |
| `?branch=<B>` filter | PASS | `api/filters.py`; read filter runs first | `tests/api/test_filtering.py` | 200, `[]` (#12,#70) |
| `?created_by=<clerk_b/manager_b>` | PASS | same | — | 200, `[]` (#13,#14,#71,#72) |
| `?salary__gte=5000` (only B qualifies) | PASS | same | — | 200, `[]` (#15,#73) |
| `?branch__name=Branch B` traversal | PASS | same | — | 200, own rows only (#18,#76) |
| reviews `?employee=<B>` / `?employee__branch=<B>` | PASS | same | — | 200; B review never shown; clerk_a sees only his own cross-branch review `REV_X`, which he created (#19,#20,#77,#78) |
| `?search=needle` / `Beta` / `Bianca` (B-only) | PASS | `api/filters.py::KarniSearchFilter` runs after read filter | `tests/api/search/*` | 200, `[]` for manager_a & clerk_a (`search2.log` #1–#4,#10–#13) |
| `?ordering=salary` | PASS (scope) | `viewsets.py` OrderingFilter | `test_ordering.py` | 200; only own rows, correctly sorted; no B rows pulled in (#26,#27) |
| `?ordering=secret_note` (write-only) | PARTIAL | `viewsets.py:235 ordering_fields="__all__"` | `test_write_only_fields_are_not_orderable` **(passes by coincidence — see counter-test)** | 200; reorders by the hidden field (oracle), own rows only (#28,#29) |
| `?ordering=created_by__password` / `deleted_at` | PARTIAL | same | — | 200; accepted and executed; value not surfaced (#31,#32) |
| `?expand=branch` | PASS | `api/optimizer.py`, scoped Prefetch | `tests/api/test_expand.py` | 200; branch embedded; no B rows (#33) |
| `?expand=created_by` (user: no routed viewset) | PASS (400) | `api/expansion.py::validate_expand` | `test_unknown_expand_key_is_400...` | 400 — `created_by` is not an expandable key here (reverse/aliasing rules); no user object embedded (#34,#92) |
| reviews `?expand=employee` across branch | PASS | `access.py::target_read_scope` scoped Prefetch | `test_to_one_expansion_into_a_scoped_target` | 200; for a review whose employee is unreadable, `"employee": null` — the cross-branch employee is **not** embedded (#35,#36 manager_a: employee=null) |
| retrieve `REV_X` (clerk_a's own review of a B employee), `?expand=employee` | PARTIAL | same | — | clerk_a 200; `"employee": null` when expanded (B employee correctly hidden), **but unexpanded the FK pk `b8ffeb64…` (a branch-B employee id) is returned** (#96,#97). The pk of an unreadable row is disclosed because the owning review is readable. Not a row leak (no B employee fields), but it is an id oracle across the branch boundary via a legitimately-owned relation. manager_a cannot reach `REV_X` at all (404, #38,#39). |
| branches `?expand=users` / `employees` (reverse) | PASS (400) | `api/expansion.py` | `test_reverse_relation_expandable_only_when_listed` | 400 (reverse relations not expandable unless listed) (#40,#41,#98,#99) |
| crafted ids: random uuid / `abc` / `1 OR 1=1` / trailing junk / uppercase / no-dashes / empty | PASS | `get_object` + DRF uuid converter | — | all 404 (empty id → Django URL 404). No 500, no SQL error, no scope bypass (#42–#48,#100–#106) |
| POST review with `employee=<B id>` (relation PK out of scope) | PASS | `serializers.py::KarniPrimaryKeyRelatedField.get_queryset`→`readable()` | `test_relation_pk_outside_the_target_scope_is_invalid` | clerk_a 400 `{"employee":["Invalid pk \"b8ffeb64…\" - object does not exist."]}` — out-of-scope pk indistinguishable from missing. manager_a got 403 (no `review:add` grant, gate first). (#49,#107) |
| POST review with random uuid | PASS | same | — | 400 "object does not exist" (#50,#108) |
| POST employee into branch B (create) | N-A (no tenant guard on create) | `perform_create` stamps owner only | — | 201 — create is gated by the `add` grant, **not** scoped to the user's branch; both clerk_a and manager_a can create a branch-B employee (`branch` is a free body field). Expected: Karni has no "create only within my scope" rule (ADR 0002 P2). A planted row is owned by the creator, so it does not expose existing B data; worth noting as a write-side scope gap. (#52,#110) |
| POST employee with `created_by=<other user>` (body chooses owner) | PASS | `perform_create` stamps `created_by=request.user`; owner field read-only in serializer | `test_create_gate_and_owner_stamping`; `test_owner_field_is_read_only_in_the_generated_serializer` | 201 but `created_by` = the requester, not the body value (#53,#111) |
| PATCH own row `created_by=<clerk_b>` (re-own) | PASS | owner field read-only | same | 200 but `created_by` unchanged (#121,#122) |
| `?page_size=1000` | PASS | `pagination.py` hard cap 100 | `test_api/test_pagination.py` | 200; only the rows in scope returned (cap not reached here) (#54,#112) |
| my-employees retrieve another A-user's row | PASS | `Owned("created_by")` | `test_access.py` | 404 (#57,#115) |
| my-employees retrieve B row | PASS | same | — | 404 (#58,#116) |

### Write-scope escape via a legitimate update

| Attempt | Verdict | impl | Observed |
|---|---|---|---|
| manager_a PATCH own-branch `emp_a2` `branch=<B>` (move a row he owns into the other branch) | N-A / expected | `write=Can('hr.employee:change')`, `branch` is writable | 200; afterwards manager_a can no longer see it (404, #118) and manager_b now can (200, #119). Moving a row out of your own scope is allowed because `branch` is an ordinary writable field; there is no "cannot move a row out of my scope" invariant. Not a read leak; a data-integrity consideration for row-scoped models. |

### 404 vs 403 split

| Attempt | Verdict | impl | Observed |
|---|---|---|---|
| readable-but-not-writable → 403 | PASS | `AccessPermission.has_object_permission` | staff PATCH `/my-employees/<A row>` → **403** `{"detail":"...this row is readable but the action requires Owned('created_by')."}` (#127); blind PATCH/DELETE/approve → 403 with the required `Can(...)` (#123–#125) |
| out-of-scope detail → 404 not 403 | PASS | `get_object` | manager_a retrieve `emp_b1` → **404** naming the read scope (#128) |
| anonymous list/retrieve/branches | PASS | gate | 401 (#130–#132) |
| control: manager_a approve own-branch row | PASS | action grant | 200 `{"approved":"…"}` (#129) |

### Field-level visibility

| Attempt | Verdict | impl | Observed |
|---|---|---|---|
| a role that may see employees but not `salary` | UNVERIFIED / N-A (feature absent) | — | ADR 0002 P3 (field-level visibility) is **unbuilt**. The only field-hiding is `APIMeta.write_only`/`exclude`, which apply to everyone, not per role. `payroll_blind` sees `salary` in every row (`scope.log` #126). There is no per-role field mechanism to break, so recorded as a gap, not a pass. |
| write-only `secret_note` hidden from responses | PASS | `serializers.py` build_serializer; `api/filters.py::_api_filterable_names` | response component `HrEmployee` has no `secret_note`; request component `HrEmployeeRequest` has it; `?secret_note=`/`?secret_note__icontains=` are **not** filterable (ignored — list unchanged, #16,#17,#74,#75) |
| write-only field orderable | PARTIAL (leak-adjacent) | `viewsets.py:235` | see LEAKS; counter-test below |
| write-only field as search oracle | PARTIAL | fixture put it in `search_fields` | `blind` search `A-SECRET-one` → noted rows (`search2.log` #19) |

### Admin (is_staff)

| Attempt | Verdict | impl | Observed |
|---|---|---|---|
| manager_a / staff, **no** Django model perms | PASS (locked out) | Django model-permission gate | every `/admin/hr/*` changelist/change/add → **403**; `/admin/hr/user/` → 404 (user admin registered only for default model) (`admin.log` #3–#12,#15–#24) |
| manager_a **with** `view/change_employee`+`view_review` group perms | **FAIL** | `karni/admin/base.py`,`soft_delete.py` (no row scope) | changelist 200 count **9**, branch-B rows + salary 9000 shown; B change form shows salary + `secret_note`; edit of a B row persisted; `?q=needle` and `?branch=<B>` and autocomplete all surface B rows (`admin2.log`). See LEAKS. |
| superuser `root` | N-A | superuser sees all by convention | 200 everywhere, count 9, secrets shown — expected for a superuser (`admin.log` #26–#36) |

### Routes that do not exist (gaps — nothing to leak)

| Route | Verdict | Observed |
|---|---|---|
| CSV/XLSX export (`/export/`, `?format=csv`, `.csv`, `/csv/`, `/download/`) | N-A (absent) | all 404 (`routes.log` #1–#8). ADR 0002 P6 unbuilt. |
| import (`GET/POST /import/`) | N-A (absent) | GET 404; POST 405 "Method POST not allowed" (no action exists) (#14,#23) |
| change-history (`/<id>/history/`, `/history/`, `/api/history/`, `/api/audit/`) | N-A (absent) | 404 (#9–#13). ADR 0002 P4 unbuilt. `AuditedModel` records who/when, not what. |
| `/api/roles/`, `/api/permissions/`, `/api/role-permissions/`, `/api/users/`, `/api/groups/` | N-A (absent) | 404 — Role/RolePermission/User are **not** API resources; no write path (#16–#19, privesc #10–#15) |
| `/api/auth/sync-roles/`, `/api/auth/roles/`, `/api/auth/users/` | N-A (absent) | 404 — sync-roles is a management command only, admin/CLI (#20–#22, privesc #16,#17) |

### OpenAPI schema

| Attempt | Verdict | impl | Observed |
|---|---|---|---|
| `/api/schema/` anonymous | PASS (by design) | drf-spectacular; `SpectacularAPIView` default AllowAny | 200; full schema served to anyone. This is the stock scaffold wiring (`config/urls.py`). It exposes paths, the `x-karni-access` predicate per op, and component field lists — **design hints, not data**. |
| schema differs per role / hides fields | PASS (identical) | `api/schema.py` | schema byte-identical for manager_a, clerk_a, blind (`routes.log` "schema identical across roles: True"). No per-role schema (P3 unbuilt), so nothing role-specific leaks. |
| write-only field in schema | PASS | COMPONENT_SPLIT_REQUEST | `secret_note` appears only in `HrEmployeeRequest`/`PatchedHrEmployeeRequest`, never in the `HrEmployee` response component |
| `x-karni-access` exposure | PASS (intended) | `access.py::describe` | every op carries its predicate, e.g. `GET /api/employees/ {"can":["hr.employee:view"]}`, `PATCH /api/my-employees/{id}/ {"owned":"created_by"}`. Documented display hints; server still enforces. |

### Auth / tokens / abuse

| Attempt | Verdict | impl | test | Observed |
|---|---|---|---|---|
| access-token expiry (lifetime 1 min) | PASS | `conf/base.py` SIMPLE_JWT ACCESS_TOKEN_LIFETIME | `tests/accounts/test_login_logout.py` | fresh token 200; after 65 s → **401** `{"detail":"Given token not valid...","messages":[{"token_type":"access","message":"Token is expired"}]}` (`auth.log` #1–#3) |
| logout blacklists refresh | PASS | `accounts/api/views.py::LogoutView` | `test_jwt_logout_blacklists_posted_refresh_token` | logout 204; reusing that refresh → **401** `{"detail":"Token is blacklisted"}` (#4,#5) |
| access token after logout | PASS (documented window) | by design (no per-request access blacklist) | docs/accounts.md JWT mode | access token **still works** right after logout — `GET /me/` 200, `GET /employees/` 200 (#6,#7). This is the documented ≤15-min (here ≤1-min) window; not a defect. |
| refresh rotation + replay | PASS | ROTATE_REFRESH_TOKENS/BLACKLIST_AFTER_ROTATION | `test_jwt_refresh_rotates_and_blacklists_previous_token` | rotate 200; replay old refresh → **401** "Token is blacklisted" (#8,#9) |
| forged `alg=none` / garbage bearer | PASS | SimpleJWT signature check | — | **401** both (`auth2.log` #1,#2) |
| verification-link replay | PASS | `accounts/tokens.py::consume_token` single-use | `test_verify_email_replay_rejected` | token captured from file email backend; verify #1 **200**, replay **400**, garbage **400** (`auth2.log` #3–#6; token in `verify-email.txt`) |
| password-reset enumeration | PASS | `PasswordResetView` always-200 | `test_reset_request_is_enumeration_silent` | unknown and known address both **200**, identical body (#7,#8) |
| register/email-change enumeration | ACCEPTED (documented) | `RegisterSerializer.validate_email` | docs/accounts.md "Enumeration posture" | duplicate email → **400** "A user with this email address already exists." — the documented, accepted reveal (#9) |
| login rate limit (per-IP, doc 10/min) | PASS | `accounts/api/throttles.py` | `tests/accounts/test_ratelimit.py` | first **429** at attempt **11**, `Retry-After: 59` (`auth2.log` #10–#23) |
| login rate limit (per-account, rotating IP, doc 10/hour) | PASS | `AccountRateThrottle` keyed on email hash | `test_same_email_across_ips_is_throttled` | first **429** at attempt **11**, `Retry-After: 3599` — rotating `X-Forwarded-For` did not evade it (#24–#37) |
| password spraying: distinct accounts, rotating `X-Forwarded-For` | PARTIAL (deployment caveat) | per-IP throttle trusts `NUM_PROXIES=1` | docs: Caddy fronts the stack | **no 429** in 14 attempts (#38–#51). With `KARNI_NUM_PROXIES=1` (the default), Django trusts the last `X-Forwarded-For` hop; a client talking to Django directly (no Caddy) can rotate that header to defeat the per-IP login throttle. The per-account throttle still bounds single-account attacks, but low-and-slow spraying across many accounts from spoofed IPs is unbounded when the documented proxy is absent. Not a flaw in Karni's code — the shipped Caddy sets the real client IP — but a sharp edge: never expose Django directly. |
| register rate limit (doc 10/hour) | PASS | throttle `auth.register` | — | first **429** at attempt **11** (#52–#65) |
| password-reset rate limit (doc 5/hour) | PASS | throttle `auth.password_reset` | — | first **429** at attempt **6** (#66–#74) |

### Privilege escalation

| Attempt | Verdict | impl | test | Observed |
|---|---|---|---|---|
| PATCH `/api/auth/me/` with is_staff/is_superuser/groups/roles/branch/email/password | PASS | `accounts/api/serializers.py::MeSerializer` read_only + `MeView` patch-only safe fields | — | **200** but response unchanged: `roles` still `["clerk"]`, email unchanged; `is_staff`/`is_superuser`/`groups`/`branch`/`password` all ignored. Listing employees afterwards still own-only (`privesc.log` #2,#4,#5) |
| PUT `/api/auth/me/` | PASS | `MeView.http_method_names` | — | **405** "Method PUT not allowed" (#3) |
| register with is_staff/is_superuser/groups/roles/branch/email_verified | PASS | `RegisterSerializer` (only email/password/names) | — | **201** but new user has `roles:[]`, `email_verified:false`; `evil` then gets **403** on `/api/employees/` (#6–#8). The privilege fields were dropped. |
| any writable path to Role/RolePermission/Group/User, or sync-roles over HTTP | PASS | no such route registered | `tests/accounts/test_roles.py` (sync is a command) | all **404** (privesc #10–#17). sync-roles is admin/CLI only. |
| superuser grant convention | N-A | `roles.py::grants_for` | `test_superuser_holds_everything` | superuser holds every permission `all` by convention — intended |

---

## Counter-test (shipped test is coincidentally green)

`tests/api/test_ordering.py::test_write_only_fields_are_not_orderable` arranges
`older.internal_note="zzz"`, `newer.internal_note="aaa"`, so note-ascending
`[newer, older]` equals the default `-created_at` order — the assertion
`result == default_order` holds regardless of whether the write-only field is
orderable. Swapping the notes makes the two orders differ. Run against Karni's
own fixtures/viewset (evidence `zz_counter.py`, executed with
`DJANGO_SETTINGS_MODULE=tests.settings`):

```
older.internal_note="aaa" (created_offset=-300), newer.internal_note="zzz"
default (-created_at):        [newer, older]
?ordering=internal_note:      [older, newer]   <-- reordered by the write-only field
AssertionError: write-only field internal_note IS orderable
```

So the write-only (and sensitive-user-field) ordering oracle is real;
`ordering_fields = "__all__"` in `karni/api/viewsets.py:235` is the cause, and
the shipped test does not actually prove the claim in its name.

---

## Gaps (documented but unbuilt — ADR 0002)

- **P2 row-scoping in the admin** — unbuilt → the FAIL above. `karni.admin` has
  no `get_queryset` scope; any role given Django model perms reads/writes every
  tenant's rows in the admin, including the API's write-only field.
- **P2 create/update scope** — a row can be created in, or moved into, another
  branch via the writable `branch` field; there is no "within my scope" write
  invariant. Create/move are owner-stamped but not branch-bounded.
- **P3 field-level visibility** — unbuilt → no per-role field hiding; `salary`
  is visible to every role that can read the row; the schema is identical for
  all roles.
- **P4 change history** — no history model/endpoint/admin tab.
- **P6 import/export** — no export or import routes exist.

These cannot leak "what does not exist" at the API layer today (every probe
404s), but P2-admin **does** leak now, because the admin surface exists while
its scope does not.

---

## Findings ranked by what they cost a real user

1. **Admin has no row scope (P2-admin) — a live cross-tenant data + write leak
   the day a non-superuser role is let into the admin.** A branch manager given
   the ordinary Django `change_employee` permission reads every branch's
   salaries and secret notes and can edit other branches' rows. This is the
   single highest-blast-radius finding: the API enforces isolation flawlessly,
   so an operator reasonably assumes the admin does too — and it does not. Until
   P2-admin ships, the safe posture is "only superusers in the admin," which
   must be stated loudly (it is only in an ADR today).
2. **Password spraying when Django is exposed without the Caddy proxy.** The
   per-IP login throttle trusts `X-Forwarded-For` (`NUM_PROXIES=1`); a direct
   client rotating that header evades it for distributed, cross-account spraying.
   The per-account throttle still protects a single targeted mailbox. Cost: real
   if anyone runs Django on a public port without the shipped reverse proxy.
3. **Write-only / sensitive fields are orderable (and, if listed, searchable).**
   An ordering/search oracle over a hidden column. Low cost for scoped roles
   (only reorders rows you can already read); higher for an all-rows role that
   is supposed to be blind to a field — but that role cannot exist yet (P3), so
   today it mostly means `secret_note` and user `password`/`last_login` can
   order the list. Still a correctness gap, and the shipped test gives false
   assurance.
4. **Relation-pk disclosure through a readable owning row.** The FK pk of an
   unreadable row is returned when the owning (readable) row is serialized
   unexpanded (expansion itself renders `null`). An id oracle across the
   boundary, no field data. Minor.
5. **No create/move scope bound.** Cosmetic data-integrity sharp edge; the
   planted row is owned by its creator and exposes no existing data.

Everything else the brief asked to break held: list/retrieve/patch/delete/
approve/expand/filter/search across the branch boundary all refuse; relation-pk
validation, owner stamping, the 404-vs-403 split, token expiry, logout
blacklisting, verification-replay, reset enumeration silence, the documented
rate limits, and every self-grant attempt (me/, register, direct Role writes)
all behaved exactly as documented.

---

## Blunt assessment

The API access model is genuinely solid and I could not get a single branch-B
row out of it as manager_a or clerk_a: the row filter is authoritative and runs
before filtering, searching, ordering and expansion, so none of those classic
side channels widened the scope, out-of-scope detail is a 404 that names the
scope without an existence oracle, relation pks and `?expand=` honour the
target's read scope, owner fields cannot be chosen by the body, and `/me/` and
`register` silently drop every privilege field. The auth surface is equally
disciplined — short access tokens, blacklist-on-logout, single-use verification
tokens, enumeration-silent reset, and throttles that land exactly where the docs
say. The real exposure is the seam the ADR already admits: the admin enforces
Django's model permissions but **none** of Karni's row scope, so the moment you
let a branch manager into the admin the way every Django shop does, branch
isolation evaporates there and the write-only field is readable — a leak that is
invisible from the API and will bite whoever assumes the two surfaces share a
policy. Fix P2-admin, stop putting write-only fields in `search_fields`, and
either restrict `ordering_fields` to serializer-visible fields or rewrite the
ordering test so it actually proves its own claim.

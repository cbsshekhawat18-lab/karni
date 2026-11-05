---
description: "karni.admin: every model gets a derived django-unfold admin with columns, filters, search and autocompletes, and how to override any part of it."
---

# karni.admin

No project writes `admin.py` for routine models. When Django starts,
`karni.admin` autodiscovers every unregistered concrete model and registers a
derived admin on a django-unfold UI. A model with zero admin code appears
fully configured, with sensible columns, filters, search, date drilldown and
audit fields read-only.

Scope note (v0.1): third-party apps that register their own admins
(django-celery-beat/results, SimpleJWT's token blacklist, `auth.Group`, …)
keep their stock admin classes, because autodiscovery never re-registers an
existing admin. A re-registration pass that restyles those is future work.

## How registration works

`KarniAdminConfig.ready()` runs `karni.admin.autodiscover()` (disable with
`KARNI_ADMIN_AUTODISCOVER = False`). For each concrete model (proxies
included) it derives a `KarniModelAdmin` subclass and registers it on the
site named by `KARNI_ADMIN_SITE` (dotted path, default
`"django.contrib.admin.site"`). Skipped:

- Models already registered. Project `admin.py` files and third-party apps
  run first, so **explicit registration always wins**.
- Models matched by `KARNI_ADMIN_EXCLUDE`, which takes app labels or
  `app_label.ModelName` entries. The default is
  `["sessions", "contenttypes", "admin", "auth.Permission",
  "django_celery_results.ChordCounter"]` (env: comma list).
- Models whose `AdminMeta.exclude` is `True`.
- `AbstractBaseUser` subclasses, unless their `AdminMeta` sets
  `register = True`. The default user model is covered explicitly by
  `karni.accounts`' `KarniUserAdmin` (see [docs/accounts.md](accounts.md)).

A second pass fills in `autocomplete_fields` for FK/M2M fields whose target
admin (on the same site) has search fields. `autodiscover()` is idempotent
and accepts `site=` for custom sites.

### App ordering

`karni_settings()` places `unfold` before `django.contrib.admin` (validation
enforces this even for a hand-written `INSTALLED_APPS`) and `karni.admin`
last. Keep `karni.admin` last. An app listed *after* it whose `ready()`
registers admins will hit `AlreadyRegistered` against the auto-derived admin.
Either keep such apps before `karni.admin` or exclude their models via
`KARNI_ADMIN_EXCLUDE`. (`unfold.contrib.filters` is not installed in v0.1.
Adopting it for nicer FK filters is a noted follow-up.)

## What gets derived

Audit fields (`id`, `created_at`, `updated_at`, `deleted_at`), UUID pks and
password-named fields are skipped everywhere. Password-named fields are also
excluded from forms.

| attribute | rule | cap |
|---|---|---|
| `list_display` | declaration-order Char/Slug/Email/URL/numeric/Boolean/Date(Time)/FK fields (never Text/JSON/File/Image/M2M), falling back to `__str__` | `KARNI_ADMIN_LIST_DISPLAY_MAX` (6) |
| `list_filter` | booleans, choice fields, FKs (`RelatedOnlyFieldListFilter`), date/datetime | `KARNI_ADMIN_LIST_FILTER_MAX` (6) |
| `search_fields` | Char/Slug/Email/Text without choices | `KARNI_ADMIN_SEARCH_MAX` (5) |
| `date_hierarchy` | first declared non-audit date field, else `created_at` | none |
| `readonly_fields` | audit fields present on the model + `AdminMeta.read_only` | none |
| `list_select_related` | FKs appearing in the derived `list_display` (no N+1 changelists) | none |
| `autocomplete_fields` | FK/M2M whose target admin has search fields (second pass) | none |

Each rule is a pure function in `karni.admin.derive` and a classmethod hook
on `KarniModelAdmin`. Override either one per project.

Documented v0.1 costs: `RelatedOnlyFieldListFilter` issues a DISTINCT
subquery per FK filter on the changelist, and the `created_at` fallback puts
a date drilldown on every `BaseModel` changelist. Trim with `AdminMeta` if a
table is huge.

## Per-model overrides: `AdminMeta`

The admin twin of `APIMeta`, declared on the model:

```python
class Invoice(BaseModel):
    ...
    class AdminMeta:
        list_display = ["number", "customer", "total"]
        list_filter = ["status"]
        search_fields = ["number"]
        read_only = ["total"]          # extends derived readonly_fields
        date_hierarchy = "issued_at"
        ordering = ["-issued_at"]
        extra = {"list_per_page": 25}  # any ModelAdmin attrs, applied last
```

Other recognized attrs are `exclude = True` (skip registration),
`inline_on = "fk_field"` and `register = True` (opt an `AbstractBaseUser`
subclass in). `inline_on` goes on the child side and generates a
`TabularInline` on the parent's admin. A list of FK names is allowed, and the
child stays registered on its own too. `extra` is the catch-all escape hatch:
it takes anything a `ModelAdmin` accepts.

Precedence: explicit `admin.site.register` (project `admin.py`) >
`AdminMeta` > derived defaults.

## Who may open a page

A staff user opens a model's admin page for an action when they hold the
grant for it through a role (`app_label.model:<action>`, see
[roles as data](accounts.md#roles-as-data)), or Django's model permission
for it. The grants are the same data the API reads for `access = Granted()`,
so a role that may change orders through the API may change them in the
admin too, and no Django permission needs ticking:

```python
KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "front_desk": {"grants": {"clinic.appointment:*": "all", "clinic.patient:view": "all"}},
}
```

A person with staff status and the `front_desk` role sees Appointments and
Patients on the admin index, opens and changes appointments, and reads
patients. The index, the app pages and the sidebar list exactly the models
the user may open. Every other page is a 403.

- Signing in to the admin still needs `is_staff` (Django's own rule). A
  role alone never opens the admin.
- Superusers hold every grant.
- Rows still follow the grant's scope (below), and a [veto](#vetoes) still
  refuses an action.
- A user without a grant for a model keeps Django's model permissions for
  it, as before.
- Inlines follow the same rule for the inline's model. Generated inlines
  have it, and `karni.admin.KarniInlineMixin` gives it to your own:
  `class LineInline(KarniInlineMixin, TabularInline)`.
- Only a superuser changes `is_superuser` and `user_permissions`, or edits
  or deletes a superuser's account, on `KarniUserAdmin`. A grant on the user
  model still lets its holder give roles to people, so grant
  `<user model>:change` only to someone trusted with every role.

`KARNI_ADMIN_GRANTS_OPEN_PAGES = False` restores the rule before 0.5.0:
only Django's model permissions open pages, and the grants decide the rows.
To keep one admin on Django's permissions, override `granted()`:

```python
class LedgerAdmin(KarniModelAdmin):
    def granted(self, request, action):
        return False  # Django's model permissions only, for this page
```

## Row scope

The admin shows the rows the user's grants reach (ADR 0002, P2). That is the
same answer the API gives for `access = Granted()`. A grant or a Django
permission opens a page ([above](#who-may-open-a-page)). The roles' grants
(`KARNI_ROLES` → `RolePermission`, see [roles as data](accounts.md#roles-as-data))
decide which rows those pages show and accept:

- `get_queryset()` keeps only the rows the user's `view` grants reach, so the
  changelist, its search and list filters, the autocomplete endpoint and
  every action start from the same set. A branch manager sees their
  branch. A staff user with Django permissions but **no grant sees
  nothing**. Superusers hold every grant.
- `has_view_permission`, `has_change_permission` and `has_delete_permission`
  with an object also require the row to be inside the matching grant's
  scope, so a change-form URL for another scope's row is refused (and the
  changelist never offered it).
- FK and M2M widgets list only target rows the user may view, which is what
  the API's relation fields accept.

A soft-deleted row inside the scope stays reachable (the owner can restore
it). An admin that must show every row to whoever may open it opts out:

```python
class SupportConsoleAdmin(KarniModelAdmin):
    scope_exempt = True
    scope_exempt_reason = "support staff look up any customer's rows"
```

The reason is required (`E210` without it), and `karni check` prints every
exemption in the project on each run. Viewsets have the same switch
([Access control](api.md#access-control)). The one-line test that a role
cannot reach another scope's rows through the admin is
[`assert_isolated`](testing.md#isolation-the-test-people-forget).

## Field visibility

`Karni.field_roles` ([API reference](api.md#field-visibility)) applies to
the admin too. A field the staff user may not read is absent from the
changelist columns, the change form (fields and fieldsets), search, list
filters and sortable columns, and a changelist lookup on it (`?salary__gte=`)
is refused. A field they may read but not change is shown read-only. No
admin class needs to know. The hooks (`get_list_display`, `get_fields`,
`get_search_fields`, `get_sortable_by`, `get_readonly_fields`,
`lookup_allowed`, …) call `super()` and then drop what the user's roles do
not reach, so an explicit `AdminMeta` or subclass still works.

## Change history

A model that opts in with `class Karni: audit = True` gets its field-level
changes on the History tab of its change page, with the same visibility
rules applied. The tab shows date, user, action and each field's old → new,
above Django's own admin-action log. See [change history](change-history.md).

## Permission matrix

Roles → **Permission matrix** is the screen that changes who may do what
without a deploy. It has roles across, models down, one scope selector per
action, bulk selectors per row and column, a confirmation diff before
anything is saved, and the matrix's own change history underneath. **Effective
permissions** (on the same changelist, and as a button on every user's change
page) answers "why can this person see this?". It lists every permission a
user holds, with the role that grants it and at which scope. Both pages are
gated on the grants (`karni_accounts.rolepermission:view` to look, `:change`
to edit) and work at tablet width. The rules, the guard rails and the API are
in [accounts](accounts.md#permission-matrix).

## The API cache screen

The admin index lists **Karni → API cache** (`<admin>/karni/api-cache/`), for
superusers only. It shows whether [response caching](api.md#response-caching)
is on, the cache backend and alias in use, how a clear works with that
backend (`delete_pattern` deletes the entries, otherwise the version tokens
are replaced), the daily flush `KARNI_API_CACHE_FLUSH` schedules, and every
routed resource with its TTL and the models it reads. **Clear everything**
drops every cached response, and **Clear** on a row drops one resource's.
The bulk actions of every changelist (delete selected, restore, your own)
invalidate the cache once per action, not once per row.

Override / escape hatch: subclass `karni.admin.cache.ApiCacheScreen` (its
`has_permission(request)` lets a role in) and call
`karni.admin.cache.install(site, screen=MyScreen)` from an `admin.py`. The
template is `karni_admin/api_cache.html`.

## Import and export

Every changelist has **Export selected as CSV / XLSX** and an **Import**
button. Export takes the selection, or every filtered row with "select all",
through the row scope and the role's field visibility. Import lets you
upload, map columns to fields, preview the dry run and commit, all on one
page, with progress for large files and a downloadable template.
`karni_transfer = False` on an admin class removes both. See
[import and export](import-export.md).

## Vetoes

The admin honours [`karni.vetoes`](api.md#vetoes) the way the API gate does.
`has_add_permission`, `has_change_permission` and `has_delete_permission`
also require that no registered veto refuses the action. `get_actions`
drops vetoed action names (`delete_selected`, `export_csv`, …) from the
menu, and the *Import* page refuses when `import` is vetoed.
`KarniAdminMixin.vetoed(request, action)` is the one call behind all of
them, so use it in a custom view. The `karni-impersonation` module registers
the veto that blocks dangerous actions while a support user acts as someone
else.

## External tables and views

!!! warning "Experimental"
    `KarniModelAdmin.is_read_only` is [experimental](stability.md#experimental-names).

An [external model](models.md#external-tables-views-and-a-second-database)
(`class Karni: external = True`) is registered like any other, with derived
columns, filters, search and row scope. Unless it declares `writable =
True`, its admin is read-only: no add, change or delete permission, so the
change view shows every field read-only, the bulk delete action and the
import page are gone, and the export actions stay. An inline of such a model
(`AdminMeta.inline_on`) shows its rows and changes none.
`KarniModelAdmin.is_read_only()` decides it: override it to make one admin
writable, or any admin read-only. A model on a second database
(`Karni.database`) is read and written there.

## Tree models

!!! warning "Experimental"
    The tree changelist (`karni.admin.tree`, `tree_changelist_max_rows`) is
    [experimental](stability.md#experimental-names).

A [tree model](models.md#tree-models)'s changelist lists the rows in tree
order, a parent and then its branch, with the name indented by depth
(the `tree_label` column, first in the derived columns). Filters and search
still apply, and a row whose parent they leave out starts a branch. A list
sorted by a column is flat, and so is one with more than
`tree_changelist_max_rows` (10,000) rows. Set it to 0 on an admin to turn
tree order off.

The menu of [navigation from data](navigation.md) (`KARNI_NAVIGATION =
"db"`, experimental) is such a tree: *Navigation items* lists the entries in
tree order, and its *Menu preview* button shows the menu one user gets.

## Soft-deleted models in the admin

For `karni.models.SoftDeleteModel` subclasses the derived admin is
soft-delete aware:

- The changelist defaults to **alive rows only**, and the "deleted" filter
  switches to only-deleted or everything. The change form can open deleted
  rows. The admin queryset lifts the `soft_delete` scope, and only that one
  (`objects.without("soft_delete", reason=...)`), so any other scope, such as
  a tenant, still applies.
- Django's built-in *delete selected* action stays and is **soft** on soft
  models (it is a real delete everywhere else). Extra actions: *restore
  selected*, and *hard delete selected*, which is superuser-only and routed
  through Django's usual confirmation page.
- Autocomplete responses only offer alive rows. FK fields pointing at a
  soft-delete model still validate rows that already reference a deleted
  object (the current value is kept in the field's queryset, and new choices
  stay alive-only).

Behavioural fine print (by design, see the `karni/models.py` docstrings):

- Soft deletes send **no** `pre_delete`/`post_delete` signals and do **not**
  cascade to related rows. Hard deletion is only ever the explicit
  `hard_delete()` / admin hard-delete action.
- Delete confirmation pages use Django's collector, so they list cascade
  children that a *soft* delete will not actually touch.

## Theming

The admin, the welcome page and `@karni/ui` are one product: the same
colours, radius, spacing and font stack. They share one source, `@karni/ui`'s token stylesheet
(`packages/karni-ui/src/styles.css`, published as `@karni/ui/styles.css`).
The `karni` package ships a byte-for-byte copy of it as the static file
`karni/tokens.css`, and a test fails, printing the `cp` command, until a
change to the tokens is copied. Copying a file, rather than generating a
palette, keeps a single set of values: no build step, and nothing on the
Django side to keep in step by hand.

Unfold reads the `UNFOLD` setting. Karni's default:

- Sets the site title and header from `KARNI_ADMIN_TITLE` (env, default
  `"<PROJECT_NAME> admin"`).
- Loads `karni/tokens.css` and `karni/unfold-theme.css` through `STYLES`.
  The second file draws unfold with the tokens: `@karni/ui`'s system font
  stack instead of the Inter that unfold bundles, `--karni-space-unit` as
  unfold's spacing step, text on primary buttons in the primary-foreground
  colour, and on a touch screen (`pointer: coarse`) 44px sidebar rows,
  inputs, selects and save buttons.
- Points `COLORS["primary"]` and the text colours (`COLORS["font"]`) at the
  tokens (`var(--karni-color-primary)` and tints of it), so buttons, links,
  focus rings and the active sidebar entry are `@karni/ui`'s primary in both
  themes: near-black on light, near-white on dark.
- Sets `COLORS["base"]` to the same Tailwind gray the tokens use. Unfold picks
  different steps of this scale in light and dark mode, so it holds fixed
  values rather than `var()`s, written exactly as `tokens.css` writes them.
  The test pins each step to its token.
- Sets `BORDER_RADIUS` to `var(--karni-radius-md)`, the radius of
  `@karni/ui`'s buttons and inputs.
- Shows the admin in light mode only, with no light / dark switch, through
  `THEME` (below).

`KARNI_ADMIN_THEME` (default `"light"`) sets unfold's `THEME`, so every page,
the login screen and every screenshot look the same. The other values:

```python
KARNI_ADMIN_THEME = "dark"  # dark only
KARNI_ADMIN_THEME = "auto"  # unfold's light / dark / system switch, following the system preference
```

The admin reads it on every request (`UNFOLD["THEME"]` holds
`karni.conf.admin_theme.theme`), so it works wherever `settings.py` assigns
it, and an unknown value fails startup. Setting `UNFOLD["THEME"]` yourself
wins. Dark mode is the `dark` class on `<html>`, as in `@karni/ui`.

The project's own brand comes from the file its staff app loads:
`frontend/src/karni-theme.css`, which `karni ui detect` writes. `KARNI_THEME_CSS`
names it, `karni.admin.theme.ProjectThemeFinder` serves it as the static file
`karni/project-theme.css`, and `STYLES` loads it third. One file, both
screens: see [theming](theming.md#one-theme-for-the-staff-app-and-the-admin).
To give the admin overrides of its own instead, append a static file after
Karni's three:

```css
/* static/css/admin-theme.css */
:root,
.dark {
  --karni-color-primary: oklch(0.55 0.2 250);
  --karni-color-primary-foreground: white;
}
```

```python
from django.templatetags.static import static

karni_settings(globals())

UNFOLD["STYLES"].append(lambda request: static("css/admin-theme.css"))
```

`--karni-color-*` values change the primary scale, the text colours and
Karni's own admin pages together. The neutral `base` scale is fixed, so set
`UNFOLD["COLORS"]["base"]` too if you change the greys. Other ways to change
the theme:

```python
# a static scale of your own instead of the tokens: all eleven steps, "50" to "950"
UNFOLD["COLORS"]["primary"] = MY_PRIMARY_SCALE

# unfold's own look: drop Karni's stylesheets and colours
UNFOLD["STYLES"] = []
del UNFOLD["COLORS"]

# or replace the whole setting (assign after the call: your value wins)
UNFOLD = {"SITE_TITLE": "Ops", "SITE_HEADER": "Ops"}
```

A replaced `UNFOLD` has no `SITE_LOGO` or `SITE_ICON` entry, so
`KARNI_ADMIN_LOGO` then shows nothing, and startup fails with `karni.E508`
while it is set. Change `UNFOLD` in place instead, or put the two entries
back: `"SITE_LOGO": karni.conf.admin_logo.site_logo` and `"SITE_ICON":
karni.conf.admin_logo.site_icon`.

A static primary of your own keeps Karni's `unfold-theme.css`, which colours
text on primary buttons with `--karni-color-primary-foreground`. That token is
dark in dark mode, because Karni's primary is light there. If your primary
stays dark in dark mode, set that token to a light colour for `.dark` as well.
Defining `UNFOLD` *before* the call also works, because the call uses
setdefault semantics.

Karni's own admin pages (import, the permission matrix and its review,
effective permissions) load `karni/admin-pages.css`, and `karni/tokens.css`
too when `STYLES` did not, so they keep their look even if you replace
`STYLES`. Their controls are at least 44px tall, wide tables scroll sideways
inside the page, and nothing depends on hover. To restyle them, override the
template `karni_admin/includes/page_styles.html`.

The header and login screen carry no logo by default, because the admin is
yours, not Karni's. `KARNI_ADMIN_LOGO` adds one. `"karni"` uses Karni's own
mark (the black-ground mark in light mode, the light-ground one in dark mode,
the small variant as the site icon), or you can give static paths of your own:

```python
KARNI_ADMIN_LOGO = {"light": "img/mark.svg", "dark": "img/mark-dark.svg", "icon": "img/icon.svg"}
```

Each value is passed to `static()`, and `dark` and `icon` fall back to
`light`. `KARNI_ADMIN_LOGO = None` (the default, also the env value `""`)
leaves the text header.

The admin reads the setting on every request: `UNFOLD["SITE_LOGO"]` and
`UNFOLD["SITE_ICON"]` hold `karni.conf.admin_logo.site_logo` and
`site_icon`, which unfold calls with the request. So the setting works
wherever `settings.py` assigns it, above or below `karni_settings()`, and an
invalid value fails startup validation (`E303`). The login screen shows the
same logo above its title: `karni.admin` gives the admin site the
`karni_admin/login.html` template, which extends unfold's login page. A site
that sets its own `login_template` keeps it.

More escape hatches:

- `KARNI_ADMIN_BASE` (default `"unfold.admin.ModelAdmin"`) is the base class
  `KarniModelAdmin` extends, resolved lazily. Point it at your own subclass
  to inject behaviour into every derived admin.
- `KARNI_ADMIN_SITE` is the dotted path to the `AdminSite` instance used for
  registration and by the test/project URLconf.
- `KARNI_ADMIN_AUTODISCOVER = False` opts out entirely. Use
  `karni.admin.KarniModelAdmin` as a hand-registered base class instead.

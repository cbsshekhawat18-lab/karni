# karni.admin

No project writes `admin.py` for routine models: when Django starts,
`karni.admin` autodiscovers every unregistered concrete model and registers a
derived admin on a django-unfold UI. A model with zero admin code appears
fully configured — sensible columns, filters, search, date drilldown and
audit fields read-only.

Scope note (v0.1): third-party apps that register their own admins
(django-celery-beat/results, SimpleJWT's token blacklist, `auth.Group`, …)
keep their stock admin classes — autodiscovery never re-registers an
existing admin. A re-registration pass that restyles those is future work.

## How registration works

`KarniAdminConfig.ready()` runs `karni.admin.autodiscover()` (disable with
`KARNI_ADMIN_AUTODISCOVER = False`). For each concrete model (proxies
included) it derives a `KarniModelAdmin` subclass and registers it on the
site named by `KARNI_ADMIN_SITE` (dotted path, default
`"django.contrib.admin.site"`). Skipped:

- models already registered (project `admin.py` files and third-party apps
  run first — **explicit registration always wins**);
- models matched by `KARNI_ADMIN_EXCLUDE` — app labels or
  `app_label.ModelName` entries; default
  `["sessions", "contenttypes", "admin", "auth.Permission",
  "django_celery_results.ChordCounter"]` (env: comma list);
- models whose `AdminMeta.exclude` is `True`;
- `AbstractBaseUser` subclasses, unless their `AdminMeta` sets
  `register = True` (the default user model is covered explicitly by
  `karni.accounts`' `KarniUserAdmin` — see [docs/accounts.md](accounts.md)).

A second pass fills in `autocomplete_fields` for FK/M2M fields whose target
admin (on the same site) has search fields. `autodiscover()` is idempotent
and accepts `site=` for custom sites.

### App ordering

`karni_settings()` places `unfold` before `django.contrib.admin` (validation
enforces this even for a hand-written `INSTALLED_APPS`) and `karni.admin`
last. Keep `karni.admin` last: an app listed *after* it whose `ready()`
registers admins will hit `AlreadyRegistered` against the auto-derived admin
— either keep such apps before `karni.admin` or exclude their models via
`KARNI_ADMIN_EXCLUDE`. (`unfold.contrib.filters` is not installed in v0.1;
adopting it for nicer FK filters is a noted follow-up.)

## What gets derived

Audit fields (`id`, `created_at`, `updated_at`, `deleted_at`), UUID pks and
password-named fields are skipped everywhere; password-named fields are also
excluded from forms.

| attribute | rule | cap |
|---|---|---|
| `list_display` | declaration-order Char/Slug/Email/URL/numeric/Boolean/Date(Time)/FK fields (never Text/JSON/File/Image/M2M); falls back to `__str__` | `KARNI_ADMIN_LIST_DISPLAY_MAX` (6) |
| `list_filter` | booleans, choice fields, FKs (`RelatedOnlyFieldListFilter`), date/datetime | `KARNI_ADMIN_LIST_FILTER_MAX` (6) |
| `search_fields` | Char/Slug/Email/Text without choices | `KARNI_ADMIN_SEARCH_MAX` (5) |
| `date_hierarchy` | first declared non-audit date field, else `created_at` | — |
| `readonly_fields` | audit fields present on the model + `AdminMeta.read_only` | — |
| `list_select_related` | FKs appearing in the derived `list_display` (no N+1 changelists) | — |
| `autocomplete_fields` | FK/M2M whose target admin has search fields (second pass) | — |

Each rule is a pure function in `karni.admin.derive` and a classmethod hook
on `KarniModelAdmin` — override either per project.

Documented v0.1 costs: `RelatedOnlyFieldListFilter` issues a DISTINCT
subquery per FK filter on the changelist, and the `created_at` fallback puts
a date drilldown on every `BaseModel` changelist. Trim with `AdminMeta` if a
table is huge.

## Per-model overrides — `AdminMeta`

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

Other recognized attrs: `exclude = True` (skip registration),
`inline_on = "fk_field"` (child side: generates a `TabularInline` on the
parent's admin; a list of FK names is allowed; the child stays registered on
its own too), `register = True` (opt an `AbstractBaseUser` subclass in).
`extra` is the catch-all escape hatch — anything a `ModelAdmin` accepts.

Precedence: explicit `admin.site.register` (project `admin.py`) >
`AdminMeta` > derived defaults.

## Soft-deleted models in the admin

For `karni.models.SoftDeleteModel` subclasses the derived admin is
soft-delete aware:

- The changelist defaults to **alive rows only**; the "deleted" filter
  switches to only-deleted or everything. The change form can open deleted
  rows. The admin queryset lifts the `soft_delete` scope, and only that one
  (`objects.without("soft_delete", reason=...)`), so any other scope, such as
  a tenant, still applies.
- Django's built-in *delete selected* action stays and is **soft** on soft
  models (it is a real delete everywhere else). Extra actions: *restore
  selected*, and *hard delete selected* — superuser-only and routed through
  Django's usual confirmation page.
- Autocomplete responses only offer alive rows; FK fields pointing at a
  soft-delete model still validate rows that already reference a deleted
  object (the current value is kept in the field's queryset; new choices
  stay alive-only).

Behavioural fine print (by design — see `karni/models.py` docstrings):

- Soft deletes send **no** `pre_delete`/`post_delete` signals and do **not**
  cascade to related rows; hard deletion is only ever the explicit
  `hard_delete()` / admin hard-delete action.
- Delete confirmation pages use Django's collector, so they list cascade
  children that a *soft* delete will not actually touch.

## Theming

Unfold reads the `UNFOLD` setting. Karni's default sets the site title and
header from `KARNI_ADMIN_TITLE` (env, default `"<PROJECT_NAME> admin"`), a
neutral indigo primary color scale, `BORDER_RADIUS: "8px"` and leaves
unfold's automatic light/dark switching on. Two ways to change it:

```python
karni_settings(globals())

# 1. mutate the merged default
UNFOLD["COLORS"]["primary"]["600"] = "oklch(0.55 0.2 250)"

# 2. or replace it wholesale (assign after the call — your value wins)
UNFOLD = {"SITE_TITLE": "Ops", "SITE_HEADER": "Ops"}
```

(Defining `UNFOLD` *before* the call also works — setdefault semantics.)

The header and login screen carry no logo by default — the admin is yours,
not Karni's. `KARNI_ADMIN_LOGO` adds one: `"karni"` uses Karni's own mark
(the black-ground mark in light mode, the light-ground one in dark mode,
the small variant as the site icon), or give static paths of your own:

```python
KARNI_ADMIN_LOGO = {"light": "img/mark.svg", "dark": "img/mark-dark.svg", "icon": "img/icon.svg"}
```

Each value is passed to `static()`; `dark` and `icon` fall back to `light`.
`KARNI_ADMIN_LOGO = None` (the default, also the env value `""`) leaves the
text header.

More escape hatches:

- `KARNI_ADMIN_BASE` (default `"unfold.admin.ModelAdmin"`) — the base class
  `KarniModelAdmin` extends, resolved lazily; point it at your own subclass
  to inject behaviour into every derived admin.
- `KARNI_ADMIN_SITE` — dotted path to the `AdminSite` instance used for
  registration and by the test/project URLconf.
- `KARNI_ADMIN_AUTODISCOVER = False` — opt out entirely and use
  `karni.admin.KarniModelAdmin` as a hand-registered base class.

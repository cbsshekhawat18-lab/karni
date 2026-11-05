"""Render docs/settings.md from karni.conf.base — the settings reference is generated.

    python -m karni.conf.reference > docs/settings.md
    python -m karni.conf.reference --explain KARNI_SITE_HIGHLIGHT [--json]

Every ``KARNI_*`` setting ``karni_settings()`` defines is read out of
``karni/conf/base.py`` (its default, and the environment variable it is read
from) and paired with the one-line description in :data:`DESCRIPTIONS`.
Each module's settings are read out of its ``conf.py`` the same way
(:func:`module_settings`), with the comment above each one as its
description. ``tests/test_settings_reference.py`` fails when the page is
stale or a setting has no description, so the reference cannot drift from
the code. ``karni explain <SETTING>`` reads the same source (:func:`lookup`).

Stdlib only, and nothing is imported to be read: karni-cli loads this file
by path, so ``karni explain`` works without Django or a project.
"""

# ruff: noqa: E501  (the descriptions are prose rows of a table)
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Final

__all__ = [
    "DESCRIPTIONS",
    "DOCS_PAGE",
    "Setting",
    "anchor",
    "lookup",
    "module_conf_files",
    "module_settings",
    "render",
    "settings",
]

BASE_SOURCE: Final = Path(__file__).with_name("base.py")
#: The docs page every setting has a row on (``docs/settings.md``).
DOCS_PAGE: Final = "settings"


def _checkout_modules() -> Path | None:
    """The monorepo's ``modules/`` folder, when this file is ``packages/karni/karni/conf``'s."""
    parents = Path(__file__).resolve().parents
    if len(parents) > 4 and parents[3].name == "packages" and parents[2].name == "karni":
        return parents[4] / "modules"
    return None


#: One line per setting: what it does, and the values it takes.
DESCRIPTIONS: Final[dict[str, str]] = {
    "KARNI_AUTH_MODE": "`jwt` (SimpleJWT token pairs) or `session` (cookie auth + CSRF bootstrap). See [accounts](accounts.md#auth-modes).",
    "KARNI_2FA": "Enable TOTP two-factor auth with `django-otp` (needs `karni[2fa]`).",
    "KARNI_SOCIAL_AUTH": "Enable social login through django-allauth (`karni[social]`, session mode only).",
    "KARNI_SOCIAL_PROVIDERS": "Comma-separated allauth providers to enable, e.g. `google,github`.",
    "KARNI_SOCIAL_TOKEN_PROVIDERS": 'Experimental. The providers whose ID tokens sign users in, in both auth modes and without `KARNI_SOCIAL_AUTH`: `{"google": {"client_ids": [...]}, "microsoft": {"client_ids": [...], "tenants": [...], "trusted_tenants": [...]}, "apple": {"client_ids": [...]}}`, each with optional `require_nonce` and `class` (a dotted `IdTokenProvider` path). Each one mounts `social/<provider>/`. Needs `karni[social-token]`. See [sign-in with an ID token](accounts.md#sign-in-with-an-id-token-google-microsoft-apple).',
    "KARNI_SOCIAL_TOKEN_SIGNUP": "Experimental. What a token without an account does: `open` creates the account, `approval` creates it inactive until an administrator activates it, `existing` refuses (`E223`). `None` is `open` while `KARNI_ACCOUNTS_REGISTRATION` is on, else `existing`.",
    "KARNI_SOCIAL_TOKEN_LINK_VERIFIED": "Experimental. Link a token to the existing account with its email when the provider verified the address. `False` refuses an account that has a password (`E227`).",
    "KARNI_SOCIAL_TOKEN_LEEWAY": "Experimental. Seconds of clock skew allowed on a token's `exp`, `iat` and `nbf` (0 to 300).",
    "KARNI_SOCIAL_TOKEN_JWKS_TTL": "Experimental. Seconds a provider's signing keys (JWKS) stay in the default cache. An unknown key id fetches them again, at most once a minute per provider.",
    "KARNI_SOCIAL_TOKEN_JWKS_FETCHER": "Experimental. Dotted path of the function `(url) -> dict` that fetches a key set (HTTPS, 5 second timeout by default).",
    "KARNI_EMAIL_OTP": "Experimental. Sign-in with a code sent by email, in both auth modes: mounts `otp/send/` and `otp/verify/`. Off, both answer 404 and are absent from the OpenAPI schema. See [sign in with a code](accounts.md#sign-in-with-a-code-sent-by-email).",
    "KARNI_EMAIL_OTP_TTL": "Experimental. Seconds a sign-in code lives (60 to 3600).",
    "KARNI_EMAIL_OTP_LENGTH": "Experimental. Digits in a sign-in code (4 to 10).",
    "KARNI_EMAIL_OTP_MAX_ATTEMPTS": "Experimental. Guesses a sign-in code takes before it dies (1 to 10). A wrong guess that reaches the cap kills the code.",
    "KARNI_EMAIL_OTP_SIGNUP": "Experimental. What a code for an address without an account does: `open` creates the account when the code is verified, `approval` creates it inactive until an administrator activates it (`E224`), `existing` sends no code. `None` is `open` while `KARNI_ACCOUNTS_REGISTRATION` is on, else `existing`.",
    "KARNI_TERMS": 'Experimental. A versioned terms acceptance gate, as a dict (JSON in the environment): `{"version": "2026-11", "url": "/terms/", "required": True}`, with optional `paths` (the URL prefixes it covers, default `["/api/"]`) and `exempt` (more prefixes it leaves open). Set, it mounts `terms/` and `terms/accept/` and adds `terms` to `me/`. While it requires acceptance, a signed-in user gets 403 `E245` under `paths` until they accept the current version, staff included. `None` gates nothing. See [terms acceptance](accounts.md#terms-acceptance).',
    "KARNI_FRONTEND_URL": "The SPA's origin. It is used in account emails and, in session mode, added to `CSRF_TRUSTED_ORIGINS`, so the browser's origin must match it.",
    "KARNI_ACCOUNTS_EMAIL_BACKEND": "Dotted path of the `AccountsEmailBackend` that sends every account email: verification, password reset, email change and the sign-in code.",
    "KARNI_ACCOUNTS_AUTO_LOGIN": "Sign a user in right after registration (skips email verification as a gate).",
    "KARNI_ACCOUNTS_REGISTRATION": "Whether anyone may open an account through `register/`. `False` leaves the route out (404) and out of the OpenAPI schema, for a project whose staff create every account. While it is `True`, `karni.W102` warns for a viewset that lets every signed-in user change and delete every row. See [closing registration](accounts.md#closing-registration).",
    "KARNI_ACCOUNTS_DEFAULT_ROLES": "Roles (Django groups) every self-registered user starts with, e.g. `attendee`.",
    "KARNI_ACCOUNTS_HONEYPOT_FIELD": 'Name of the hidden registration field no person fills in. A request that fills it is accepted (202) without creating a user. `""` turns the honeypot off. See [security](security.md#what-karni-does-by-default).',
    "KARNI_ROLES": 'The project\'s roles and grants: `{slug: {name, description, system, grants: {"app.model:action": scope}}}`. Grant patterns take `*` wildcards, and the scopes are `all` / `own` / `related:<key>` / `custom:<name>` / `tree:<path>`. See [roles](accounts.md#roles-as-data).',
    "KARNI_USER_GRANTS": "Experimental. Per-user grants: while `True`, each user's `UserGrant` rows (a pattern and a scope as in `KARNI_ROLES`, with targets and an expiry) join the grants of their roles, for one more query per request. `False` (the default) reads no row. See [per-user grants](accounts.md#per-user-grants).",
    "KARNI_NAVIGATION": 'Experimental. The menu `GET /api/navigation/` gives each user: a list of items (`{"label", "route", "icon", "order", "requires"}`) and groups (`{"label", "children": [...]}`), or `"db"` for the `NavItem` table edited in the admin (add `karni.navigation` to `INSTALLED_APPS`). `requires` is `public`, `authenticated` (the default) or a permission pattern as in `KARNI_ROLES`, so role grants and per-user grants open an item. `None` (the default) mounts no route. See [navigation](navigation.md).',
    "KARNI_NAVIGATION_PAGES": "Experimental. The frontend files whose `path:` entries are the app's pages. `karni check` reports a menu item whose route none of them serves (`E533`). `[]` turns that comparison off.",
    "KARNI_ROLES_AUTOSYNC": "Reconcile the role tables with `KARNI_ROLES` after every `migrate` (`karni sync-roles` does the same by hand).",
    "KARNI_AUDIT_ASYNC": "Write change-history entries from a Celery task instead of inside the request (history becomes eventually consistent). See [change history](change-history.md).",
    "KARNI_AUDIT_RETENTION_DAYS": "Days of change history to keep. `None` (the default) keeps everything and schedules no pruning.",
    "KARNI_AUDIT_REDACT": "Field-name substrings whose values are never recorded in change history, only that they changed (default `password,token,secret,key`).",
    "KARNI_ACCOUNTS_TOKEN_TTL": "Lifetime per one-time token purpose (`verify_email`, `reset_password`, ...), as timedeltas.",
    "KARNI_ACCOUNTS_LINKS": "Frontend URL template per token purpose, with `{frontend}` and `{token}` placeholders.",
    "KARNI_AUTH_THROTTLE_RATES": "Per-scope auth throttle overrides as a JSON object. `null` disables a scope.",
    "KARNI_STORAGE": "`local` (filesystem) or `s3` (any S3-compatible service, needs `karni[s3]`).",
    "KARNI_CACHE": "`redis` (the default cache at `REDIS_URL`) or `locmem`, an in-process cache for a host run without Redis (development only: throttle counters are then per process).",
    "KARNI_SEARCH_PROVIDER": "Dotted path of the `SearchProvider` behind `?search=`. The PostgreSQL provider falls back to portable search on other databases.",
    "KARNI_API_MAX_EXPAND_DEPTH": "Deepest `?expand=` path allowed (levels of nesting).",
    "KARNI_GLOBAL_SEARCH_MIN_LENGTH": "Experimental. The shortest query `GET /api/search/` searches for. A shorter one answers no groups. See [search across models](global-search.md).",
    "KARNI_GLOBAL_SEARCH_LIMIT": "Experimental. Hits per model `GET /api/search/` returns when the request does not say (`?limit=`).",
    "KARNI_GLOBAL_SEARCH_MAX_LIMIT": "Experimental. The most hits per model a request may ask for. A larger `?limit=` is lowered to it.",
    "KARNI_GLOBAL_SEARCH_THRESHOLD": "Experimental. The trigram similarity (0 to 1) a row needs on PostgreSQL to match without containing the query. pg_trgm's own `pg_trgm.similarity_threshold` (0.3) is the floor: the index answers it first.",
    "KARNI_API_ROUTER": "Zero-argument factory returning the router `karni.api.urls` exposes.",
    "KARNI_PUBLIC_CREATE_RATE": 'The limit on each caller (the user, else the client IP) of a `create` anyone may call (`create=Public()`), unless the viewset declares `throttle = Throttle(create=...)`. `None` or `""` turns this default off. See [rate limits](api.md#rate-limits).',
    "KARNI_PUBLIC_CREATE_HONEYPOT_FIELD": 'Name of the hidden form field on a public `create`. A request that fills it is answered 202 and nothing is saved. Off for a model that has a field of that name. `""` turns it off. See [rate limits](api.md#rate-limits).',
    "KARNI_MAX_PAGE_SIZE": "Hard cap on `?page_size=` for every Karni paginator.",
    "KARNI_MAX_PAGE_SIZE_FLOOR": "The lowest value `KARNI_MAX_PAGE_SIZE` may take (the frontend's page size).",
    "KARNI_QUERY_BUDGET": 'Queries allowed per `BaseViewSet` action (`"*"` for any other), merged over the defaults. Set it per viewset with `query_budget = Budget(...)`.',
    "KARNI_QUERY_BUDGET_MODE": "`off`, `warn` (log an exceeded budget) or `raise` (fail the request, which is what the pytest plugin sets).",
    "KARNI_QUERY_LOG": "Log each request's query count, duplicates and SQL time (`QueryLogMiddleware`).",
    "KARNI_SEED_LOGINS": 'Extra `karni seed` logins with their roles, as JSON: `{"organizer@example.com": ["organizer"]}`.',
    "KARNI_API_CACHE": "Cache `BaseViewSet` list and retrieve responses, invalidated on every write. See [response caching](api.md#response-caching).",
    "KARNI_API_CACHE_TTL": "Seconds a cached response lives.",
    "KARNI_API_CACHE_ALIAS": "The Django cache alias responses are stored in.",
    "KARNI_AGGREGATE_MAX_GROUPS": "Experimental. The most groups one `GET <resource>/aggregate/` returns. A request that makes more is refused (`E387`): send `top` or narrow it with filters. See [aggregations](aggregations.md).",
    "KARNI_API_CACHE_LEGACY_HEADER": "Also send the deprecated `X-Karni-Cache` header, with a deprecation warning once per process. `X-Cache` replaces it. Set it to `False` once nothing reads the old header. Removed with the header in 1.0.",
    "KARNI_API_CACHE_FLUSH": 'A daily full flush of the response cache through Celery beat: `"HH:MM"`, or `"HH:MM Area/City"` for a timezone other than Celery\'s. `None` (the default) schedules nothing.',
    "KARNI_ADMIN_AUTODISCOVER": "Register every unregistered model in the admin at startup (`karni.admin`).",
    "KARNI_ADMIN_GRANTS_OPEN_PAGES": "A role's grant (`app.model:<action>`) opens that model's admin page for that action, inside the grant's scope. `False` restores the 0.4.0 rule: only Django's model permissions open pages. Signing in to the admin still needs `is_staff`. See [admin](admin.md#who-may-open-a-page).",
    "KARNI_ADMIN_EXCLUDE": "App labels or `app_label.ModelName` entries the admin leaves out.",
    "KARNI_IMPORT_INLINE_ROWS": "Files with at most this many rows [import](import-export.md) inside the request. Larger ones run in Celery with progress.",
    "KARNI_IMPORT_MAX_ROWS": "An upload with more rows than this is refused (`E803`). Split the file.",
    "KARNI_EXPORT_MAX_ROWS": "An [export](import-export.md) with more rows than this is refused (`E803`). Narrow the filters.",
    "KARNI_MATRIX_EXCLUDE": "App labels or `app_label.ModelName` entries the [permission matrix](accounts.md#permission-matrix) leaves out (framework internals by default).",
    "KARNI_ADMIN_BULK_EDIT_MAX": "The most rows the admin's *Edit selected* action changes at once. A larger selection gets a message and nothing changes. See [admin](admin.md#bulk-actions).",
    "KARNI_ADMIN_GUIDE": "Show the *Getting started* panel on the admin home page, and its entry in the user menu. A user can dismiss it. See [admin](admin.md#the-guide).",
    "KARNI_ADMIN_LIST_DISPLAY_MAX": "Columns a derived admin changelist shows at most.",
    "KARNI_ADMIN_LIST_FILTER_MAX": "Sidebar filters a derived admin shows at most.",
    "KARNI_ADMIN_SEARCH_MAX": "Fields a derived admin searches at most.",
    "KARNI_ADMIN_SITE": "Dotted path of the admin site models are registered on.",
    "KARNI_ADMIN_LOGO": 'Logo for the admin header and login: `karni` for Karni\'s mark, or `{"light": <static path>, "dark": ..., "icon": ...}`. Leaving it unset keeps the text header. See [admin](admin.md#theming).',
    "KARNI_THEME_CSS": 'The project\'s `karni-theme.css` (relative to the project root, or absolute), the file `karni ui detect` writes for the staff app. The admin loads it too, so one file holds the brand. `""` turns it off. See [theming](theming.md#one-theme-for-the-staff-app-and-the-admin).',
    "KARNI_ADMIN_BASE": "Dotted path of the `ModelAdmin` every derived admin is built on.",
    "KARNI_GENERATOR": 'The `<meta name="generator">` value Karni\'s public pages carry (`{% karni_seo %}`), so tools that list a site\'s technologies see Karni. It names no version on purpose. `""` turns it off and keeps a design\'s own tag.',
    "KARNI_ADMIN_PATH": "URL path the scaffold mounts the Django admin at (trailing slash). Set it to something unguessable in production.",
    "KARNI_HEALTH_CHECKS": "Dotted paths of the checks `/health/ready/` runs (database, cache, Celery by default), comma-separated in the environment. A deployment without a Celery worker leaves `karni.health.checks.check_celery` out.",
    "KARNI_READYZ_CHECKS": "Dotted paths of the checks `/readyz` runs: the database, the cache and the Celery broker by default, comma-separated in the environment. Experimental. See [deploy](deploy.md#health-checks).",
    "KARNI_HEALTH_TIMEOUT": "Seconds each readiness check may take before it counts as failed (`/readyz` and `/health/ready/`). Experimental.",
    "KARNI_LOG_QUIET_PATHS": "Paths whose healthy requests the request log skips, comma-separated in the environment (`/healthz`, `/readyz` and `/health/` by default). A request that answers 400 or more is still logged. Empty logs all. Experimental.",
    "KARNI_API_VERSION": "The current API version, such as `v1`: the API is mounted at `/api/v1/` when `config/urls.py` uses `karni.api.versions.api_urls()`. Empty (the default) leaves the API unversioned. Experimental. See [API versions](api.md#api-versions).",
    "KARNI_API_VERSIONS": 'More versions and what to say about them, as a dict (JSON in the environment): `{"v0": {"deprecated": "2026-06-01", "sunset": "2027-01-31", "notes": "https://..."}, "v2": {"router": "myproject.api.v2_router"}}`. A deprecated version sends `Deprecation`, `Sunset` and `Link` headers. Experimental. See [API versions](api.md#api-versions).',
    "KARNI_API_UNVERSIONED": "What `/api/` without a version does once a version is set: `keep` (the default, it serves the current version), `redirect` (308 to the current version) or `remove` (404). Experimental. See [API versions](api.md#api-versions).",
    "KARNI_CSP": 'Directives merged into the Content-Security-Policy every response carries, as a dict (JSON in the environment): sources are added, `None` removes a directive, e.g. `{"font-src": ["https://fonts.gstatic.com"]}`. `None` sends no policy. See [security headers](security.md#security-headers).',
    "KARNI_CSP_REPORT_ONLY": "`True` sends the policy as `Content-Security-Policy-Report-Only` (reported, not enforced), `False` enforces it. `None` follows `DEBUG`.",
    "KARNI_PERMISSIONS_POLICY": 'Browser features merged into the `Permissions-Policy` header, each with the origins allowed to use it, e.g. `{"geolocation": ["self"]}`. `None` removes a feature. `None` as the whole value sends no header.',
    "KARNI_HEALTH_CELERY_TIMEOUT": "Seconds the readiness check waits for a Celery worker to answer.",
    "KARNI_PHONE_COUNTRY_CODE": 'The country code a national phone number gets in a `PhoneField` (digits, e.g. `"44"`): `"01234 000 111"` is stored as `+441234000111`. Unset, only international numbers (`+` or `00`) are accepted. See [fields](fields.md#phonefield).',
    "KARNI_PHONE_TRUNK_PREFIX": 'The prefix a national number loses before the country code goes in front (`"0"`, `"1"` in North America, `"8"` in Russia, `""` where the number is dialled as written, as in Italy).',
    "KARNI_PHONE_NORMALIZER": "Dotted path of the function a `PhoneField`, its form field and its API field clean a number with: it takes the value as typed and returns E.164, or the value unchanged to reject it. `karni.fields.to_e164` holds Karni's rules for your own function.",
    "KARNI_THUMBNAILER": "Dotted path of the function `karni.storage.thumbnails` renders thumbnails with.",
    "KARNI_VALIDATE": "Validate the merged settings at startup (`karni.conf.validation`). `False` skips it.",
    "KARNI_REQUEST_ID_TRUST_HEADER": "Accept a client's `X-Request-ID` as the request id with `DEBUG` off. Turn it on only when the proxy in front overwrites the header on every request. It is ignored when `NUM_PROXIES` is 0. See [capture](debugging/capture.md#request-ids).",
    "KARNI_REQUEST_ID_EMAILS": "Stamp `X-Karni-Request-ID` on every outgoing email (wraps `EmailMessage.send`) and trace the send in development.",
    "KARNI_DEBUG_CAPTURE": "With `DEBUG` on, record requests, failures and a trace under `.karni/` for `karni trace`, `karni replay` and `karni explain --failure`. `False` turns it off, and with `DEBUG` off it never runs. See [capture](debugging/capture.md).",
    "KARNI_DEBUG_CAPTURE_KEEP": "How many request records, and how many failure snapshots, `.karni/` keeps (the oldest go first).",
    "KARNI_DEBUG_TRACE_DAYS": "Days of `.karni/trace/` files to keep.",
    "KARNI_EVENTS_AUTODISCOVER": "Import every app's `events.py` and `listeners.py` at startup.",
    "KARNI_SCHEDULES_AUTODISCOVER": "Import every app's `schedules.py` at startup.",
    "KARNI_PK": 'Experimental. The primary key `karni make model` writes: `uuid` (`BaseModel`) or `bigint` (`BigIntBaseModel`). The CLI reads it from a plain `KARNI_PK = "bigint"` line in `config/settings.py`, and `--pk` overrides it per model. Nothing else reads it: each model\'s class line decides its key. See [choosing the key type](models.md#choosing-the-key-type).',
    "KARNI_ARCHITECTURE": "Configuration of the architecture rules: `skip_apps`, `sql_allowed`, `http_allowed`, `dup`. See [enforcement](enforcement.md).",
    "KARNI_CHECK_CACHE": "Experimental. `karni check` keeps each file check's results under the file's hash in `.karni/local/check-cache.json`, so an unchanged file is not checked again. `False` turns it off, a path (relative to the project root) moves it. See [the check cache](enforcement.md#the-check-cache).",
    "KARNI_SUGGESTIONS": "Experimental. `karni check` and `karni doctor` print suggestions after the errors and warnings: what Karni could do that the project does by hand, with the file, line and fix (`SUG001` to `SUG007`). They never fail a run. `False` turns them off for the project. The CLI reads a plain `KARNI_SUGGESTIONS = False` line in `config/settings.py`. See [suggestions](enforcement.md#suggestions).",
    "KARNI_SCALING_ROWS": "Experimental. The two row counts the scaling check compares, small then large. A viewset's `query_scaling = Scaling(rows=..., seconds=...)` overrides them and sets a time budget. See [the scaling check](testing.md#3-the-scaling-check).",
    "KARNI_SEED_BULK_THRESHOLD": "Experimental. Rows per model from which `karni seed` inserts in bulk (a large `seed` count of `karni.yaml`). `karni seed --volume` always does. See [volume seeding](seeding.md#volume-seeding).",
    "KARNI_SEED_BATCH_SIZE": "Experimental. Rows per bulk insert of `karni seed` (`--batch-size` overrides it).",
    "KARNI_SEED_LEDGER": "Experimental. `karni seed` records the row count each table holds after a run in `.karni/local/seeded.json`, and `--volume` refuses a table holding rows no seed run left there. `False` turns it off, a path moves it.",
    "KARNI_EXPLAIN_SEQ_SCAN_ROWS": "Experimental. `karni queries --explain` flags each sequential scan on a table of this many rows or more, with the index that would serve it (PostgreSQL).",
    "KARNI_SCOPES": "The active model scopes in pipeline order. Leaving it unset runs every registered scope. See [models](models.md#scopes-the-filters-every-default-manager-applies).",
    "KARNI_PAYMENTS_PROVIDER": "karni-payments: `stripe`, `razorpay`, `test` or a dotted `PaymentProvider` path.",
}

_SECTION = re.compile(r"^\s*# --- (?P<title>.+?) -+\s*$")
_ENTRY = re.compile(r'^\s*"(?P<name>KARNI_[A-Z0-9_]+)": (?P<value>.*?)(,)?\s*$')
_ENV = re.compile(
    r'env(?:\.(?P<kind>bool|int|list|json|float|db_url|str))?\(\s*"(?P<var>[A-Z0-9_]+)"'
    r"(?:\s*,\s*default=(?P<default>.*))?\)$"
)


@dataclass(frozen=True)
class Setting:
    """One setting: its name, where it is listed, its default, its variable and what it does.

    ``module`` is the distribution of a module's setting (``karni-site``), ``""`` for
    Karni's own.
    """

    name: str
    section: str
    default: str
    env: str | None
    description: str
    module: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "anchor": anchor(self.name)}


def anchor(name: str) -> str:
    """The id of a setting's row on the settings page: ``karni_site_highlight``."""
    return name.lower()


def _literal_default(lines: list[str], start: int) -> str:
    """The value text of a multi-line literal starting at ``lines[start]``."""
    depth = 0
    collected: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        collected.append(stripped)
        depth += stripped.count("{") + stripped.count("[") + stripped.count("(")
        depth -= stripped.count("}") + stripped.count("]") + stripped.count(")")
        if depth <= 0:
            break
    text = " ".join(collected)
    text = text.split(": ", 1)[1] if text.startswith('"KARNI_') else text
    text = re.sub(r"\s+", " ", text).rstrip(",").strip()
    return re.sub(r",\s*([}\])])", r"\1", text)


def settings(source: str | None = None) -> list[Setting]:
    """Every ``KARNI_*`` setting ``karni/conf/base.py`` defines, in file order."""
    text = source if source is not None else BASE_SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()
    section = "General"
    found: list[Setting] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        heading = _SECTION.match(line)
        if heading:
            section = heading["title"].strip()
            continue
        entry = _ENTRY.match(line)
        if not entry or entry["name"] in seen:
            continue
        name, value = entry["name"], entry["value"].strip()
        seen.add(name)
        env = None
        default = value
        if value.startswith("env"):
            match = _ENV.match(value)
            if match:
                env = match["var"]
                default = (match["default"] or "—").strip()
            else:
                default = _literal_default(lines, index)
                var = re.search(r'env(?:\.\w+)?\(\s*"([A-Z0-9_]+)"', default)
                env = var.group(1) if var else None
                inner = re.search(r"default=(.*)\)$", default)
                default = inner.group(1).strip() if inner else default
        elif value in {"{", "[", "("}:
            default = _literal_default(lines, index)
        elif value.startswith("_") or value.endswith("(env)"):
            default = f"computed ({value})"
        found.append(Setting(name, section, default, env, DESCRIPTIONS.get(name, "")))
    return found


def module_settings(path: Path, module: str) -> list[Setting]:
    """The settings a module's ``conf.py`` declares in ``DEFAULTS``, read without importing it.

    Each entry of a ``DEFAULTS = {...}`` (or ``DEFAULTS |= {...}``) dict, with
    the comment lines above it as its description (an entry without one shares
    the one above), its default as written, and the variable an ``env(...)``
    call reads it from.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found: list[Setting] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AnnAssign | ast.Assign | ast.AugAssign):
            continue
        if isinstance(node, ast.AugAssign) and not isinstance(node.op, ast.BitOr):
            continue  # DEFAULTS |= {...} adds a block of settings; nothing else does
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if not isinstance(key, ast.Constant):
                continue
            comments: list[str] = []
            index = key.lineno - 2
            while index >= 0 and lines[index].strip().startswith("#"):
                comments.insert(0, lines[index].strip().lstrip("#").strip())
                index -= 1
            description = " ".join(comments) or (found[-1].description if found else "")
            env, default = None, ""
            if isinstance(value, ast.Call):
                if value.args and isinstance(value.args[0], ast.Constant):
                    env = str(value.args[0].value)
                for keyword in value.keywords:
                    if keyword.arg == "default":
                        default = ast.get_source_segment(source, keyword.value) or ""
            else:
                default = ast.get_source_segment(source, value) or ""
            found.append(Setting(str(key.value), module, _flat(default), env, description, module))
    return sorted(found, key=lambda setting: _line_of(source, setting.name))


def _flat(text: str) -> str:
    """A literal written over several lines, on one: ``["a", "b"]``, not ``[ "a", "b", ]``."""
    text = " ".join(text.split())
    text = re.sub(r",\s*([}\])])", r"\1", text)
    return re.sub(r"([\[{(])\s+|\s+([\]})])", lambda m: m.group(1) or m.group(2), text)


def _line_of(source: str, name: str) -> int:
    return source.find(f'"{name}"')


def module_conf_files() -> list[tuple[str, Path]]:
    """``(distribution, conf.py)`` of each module: the checkout's ``modules/``, else installed.

    Installed modules are found by their ``karni.settings`` entry point
    (``karni_site.conf:DEFAULTS``) and located without being imported.
    """
    checkout = _checkout_modules()
    if checkout is not None and checkout.is_dir():
        local = [
            (folder.name, folder / folder.name.replace("-", "_") / "conf.py")
            for folder in sorted(checkout.iterdir())
            if (folder / "pyproject.toml").is_file()
        ]
        return [(name, path) for name, path in local if path.is_file()]
    found: dict[str, Path] = {}
    for point in entry_points(group="karni.settings"):
        package = point.value.split(":", 1)[0].split(".", 1)[0]
        try:
            spec = importlib.util.find_spec(package)
        except (ImportError, ValueError):
            continue
        if spec is None or not spec.origin:
            continue
        conf = Path(spec.origin).with_name("conf.py")
        name = point.dist.name if point.dist is not None else package.replace("_", "-")
        if conf.is_file():
            found.setdefault(name, conf)
    return sorted(found.items())


def _all_module_settings(files: Iterable[tuple[str, Path]] | None = None) -> list[Setting]:
    found: list[Setting] = []
    for module, path in files if files is not None else module_conf_files():
        try:
            found += module_settings(path, module)
        except (OSError, SyntaxError):  # a broken install must not break the reference
            continue
    return found


def lookup(name: str, files: Iterable[tuple[str, Path]] | None = None) -> Setting | None:
    """The setting ``name`` (``KARNI_SITE_HIGHLIGHT``): Karni's own, else a module's."""
    wanted = name.strip().upper()
    for setting in settings():
        if setting.name == wanted:
            return setting
    for setting in _all_module_settings(files):
        if setting.name == wanted:
            return setting
    return None


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _call_time_section() -> list[str]:
    """The settings ``karni_settings()`` reads during the call, from ``CALL_TIME_SETTINGS``."""
    from karni.conf import CALL_TIME_SETTINGS

    lines = [
        "## Settings read during the call",
        "",
        "A few settings are read while `karni_settings()` runs, to compute other settings:",
        "",
    ]
    lines += [f"- `{name}`: {derived}" for name, derived in CALL_TIME_SETTINGS.items()]
    lines += [
        "",
        "Set them in `.env`, define them above the call, or pass them to it:",
        '`karni_settings(globals(), KARNI_AUTH_MODE="session")`. Assigned below the',
        "call, they cannot change what the call already computed from them, so startup",
        "fails with [`karni.E508`](errors.md#e508), which names the setting. Every other",
        "setting works below the call. `KARNI_ADMIN_LOGO` is one of them: the admin",
        "reads it on every request.",
        "",
    ]
    return lines


def render(found: list[Setting] | None = None, modules: list[Setting] | None = None) -> str:
    rows = found if found is not None else settings()
    module_rows = modules if modules is not None else _all_module_settings()
    out = [
        "---",
        "description: Every setting karni_settings() provides, with its default, "
        "environment variable and what it controls, generated from the source.",
        "---",
        "",
        "# Settings",
        "",
        "<!-- Generated by `python -m karni.conf.reference > docs/settings.md`; never edit by hand. -->",
        "",
        "`karni_settings(globals())` in `config/settings.py` fills the module with every",
        "Django, DRF, Celery, storage and Karni setting, most of them read from the",
        "environment (`.env` for host runs, the compose file or CI for the rest).",
        "Anything assigned *after* the call wins, and any name defined *before* it is",
        "never overwritten. The call also leaves `env`, the django-environ reader Karni",
        "reads its own defaults with, in the module, so a setting added after it reads",
        'the environment the same way: `FEATURE_X = env.bool("FEATURE_X", default=False)`.',
        "`SILENCED_SYSTEM_CHECKS` starts as an empty list, so",
        '`SILENCED_SYSTEM_CHECKS += ["karni.W967"]` silences a check without a NameError.',
        "Settings read during the call are the exception (see below).",
        "This page lists the `KARNI_*` settings. The Django and",
        "DRF settings Karni derives are documented where the feature is.",
        "",
        *_call_time_section(),
        "## All settings",
        "",
        "| Setting | Env | Default | What it does |",
        "|---|---|---|---|",
    ]
    section = None
    for row in rows:
        if row.section != section:
            section = row.section
            out.append(f"| **{section}** | | | |")
        out.append(_row(row))
    out += [
        "",
        "Settings listed as computed derive from others. The defaults of env-backed",
        "settings are what an absent variable yields. `KARNI_VALIDATE` checks the merged",
        "values at startup and reports every bad one at once (error `E504`).",
        "",
        "## Module settings",
        "",
        "Each module adds its own settings through the `karni.settings` entry point, read",
        "from its `conf.py`. They apply once the module is installed (`karni add <module>`).",
        "Assign them in `config/settings.py`. A module's README says more about each.",
        "`karni explain <SETTING>` prints any setting on this page.",
        "",
    ]
    module = None
    for row in module_rows:
        if row.module != module:
            if module is not None:
                out.append("")
            module = row.module
            out += [
                f"### {module}",
                "",
                "| Setting | Env | Default | What it does |",
                "|---|---|---|---|",
            ]
        out.append(_row(row))
    out.append("")
    return "\n".join(out)


def _row(row: Setting) -> str:
    env = f"`{row.env}`" if row.env else ""
    default = f"`{_cell(row.default)}`" if row.default and row.default != "—" else ""
    name = f'<a id="{anchor(row.name)}"></a>`{row.name}`'
    return f"| {name} | {env} | {default} | {_cell(row.description)} |"


def _explain(name: str, as_json: bool) -> int:
    """``--explain NAME``: one setting, for ``karni explain`` (the project interpreter's)."""
    found = lookup(name)
    if found is None:
        sys.stderr.write(f"No setting {name}.\n")
        return 1
    data = found.to_dict()
    try:
        from karni.links import docs_page

        data["url"] = docs_page(DOCS_PAGE, anchor(found.name))
    except ImportError:  # pragma: no cover - this file outside karni
        data["url"] = ""
    print(json.dumps(data, indent=2) if as_json else data)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--explain":
        raise SystemExit(_explain(sys.argv[2], "--json" in sys.argv[3:]))
    print(render(), end="")

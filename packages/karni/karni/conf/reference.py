"""Render docs/settings.md from karni.conf.base — the settings reference is generated.

    python -m karni.conf.reference > docs/settings.md

Every ``KARNI_*`` setting ``karni_settings()`` defines is read out of
``karni/conf/base.py`` (its default, and the environment variable it is read
from) and paired with the one-line description in :data:`DESCRIPTIONS`.
``tests/test_settings_reference.py`` fails when the page is stale or a
setting has no description, so the reference cannot drift from the code.
"""

# ruff: noqa: E501  (the descriptions are prose rows of a table)
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ["DESCRIPTIONS", "Setting", "render", "settings"]

BASE_SOURCE: Final = Path(__file__).with_name("base.py")

#: One line per setting: what it does, and the values it takes.
DESCRIPTIONS: Final[dict[str, str]] = {
    "KARNI_AUTH_MODE": "`jwt` (SimpleJWT token pairs) or `session` (cookie auth + CSRF bootstrap). See [accounts](accounts.md#auth-modes).",
    "KARNI_2FA": "Enable TOTP two-factor auth (`django-otp`; needs `karni[2fa]`).",
    "KARNI_SOCIAL_AUTH": "Enable social login through django-allauth (`karni[social]`; session mode only).",
    "KARNI_SOCIAL_PROVIDERS": "Comma-separated allauth providers to enable, e.g. `google,github`.",
    "KARNI_FRONTEND_URL": "The SPA's origin: used in account emails and, in session mode, added to `CSRF_TRUSTED_ORIGINS` — the browser's origin must match it.",
    "KARNI_ACCOUNTS_EMAIL_BACKEND": "Dotted path of the `AccountsEmailBackend` that sends verification and reset emails.",
    "KARNI_ACCOUNTS_AUTO_LOGIN": "Sign a user in right after registration (skips email verification as a gate).",
    "KARNI_ACCOUNTS_DEFAULT_ROLES": "Roles (Django groups) every self-registered user starts with, e.g. `attendee`.",
    "KARNI_ACCOUNTS_HONEYPOT_FIELD": 'Name of the hidden registration field no person fills in; a request that fills it is accepted (202) without creating a user. `""` turns the honeypot off. See [security](security.md#what-karni-does-by-default).',
    "KARNI_ROLES": 'The project\'s roles and grants: `{slug: {name, description, system, grants: {"app.model:action": scope}}}`; `*` wildcards, scopes `all` / `own` / `related:<key>` / `custom:<name>`. See [roles](accounts.md#roles-as-data).',
    "KARNI_ROLES_AUTOSYNC": "Reconcile the role tables with `KARNI_ROLES` after every `migrate` (`karni sync-roles` does the same by hand).",
    "KARNI_AUDIT_ASYNC": "Write change-history entries from a Celery task instead of inside the request (history becomes eventually consistent). See [change history](change-history.md).",
    "KARNI_AUDIT_RETENTION_DAYS": "Days of change history to keep; `None` (the default) keeps everything and schedules no pruning.",
    "KARNI_AUDIT_REDACT": "Field-name substrings whose values are never recorded in change history, only that they changed (default `password,token,secret,key`).",
    "KARNI_ACCOUNTS_TOKEN_TTL": "Lifetime per one-time token purpose (`verify_email`, `reset_password`, ...), as timedeltas.",
    "KARNI_ACCOUNTS_LINKS": "Frontend URL template per token purpose, with `{frontend}` and `{token}` placeholders.",
    "KARNI_AUTH_THROTTLE_RATES": "Per-scope auth throttle overrides as a JSON object; `null` disables a scope.",
    "KARNI_STORAGE": "`local` (filesystem) or `s3` (any S3-compatible service; needs `karni[s3]`).",
    "KARNI_CACHE": "`redis` (the default cache at `REDIS_URL`) or `locmem`, an in-process cache for a host run without Redis (development only: throttle counters are then per process).",
    "KARNI_SEARCH_PROVIDER": "Dotted path of the `SearchProvider` behind `?search=`; the PostgreSQL provider falls back to portable search on other databases.",
    "KARNI_API_MAX_EXPAND_DEPTH": "Deepest `?expand=` path allowed (levels of nesting).",
    "KARNI_API_ROUTER": "Zero-argument factory returning the router `karni.api.urls` exposes.",
    "KARNI_MAX_PAGE_SIZE": "Hard cap on `?page_size=` for every Karni paginator.",
    "KARNI_MAX_PAGE_SIZE_FLOOR": "The lowest value `KARNI_MAX_PAGE_SIZE` may take (the frontend's page size).",
    "KARNI_QUERY_BUDGET": 'Queries allowed per `BaseViewSet` action (`"*"` for any other); merged over the defaults. Per viewset: `query_budget = Budget(...)`.',
    "KARNI_QUERY_BUDGET_MODE": "`off`, `warn` (log an exceeded budget) or `raise` (fail the request; what the pytest plugin sets).",
    "KARNI_QUERY_LOG": "Log each request's query count, duplicates and SQL time (`QueryLogMiddleware`).",
    "KARNI_SEED_LOGINS": 'Extra `karni seed` logins with their roles, as JSON: `{"organizer@example.com": ["organizer"]}`.',
    "KARNI_API_CACHE": "Cache `BaseViewSet` list and retrieve responses (`karni.api.caching`).",
    "KARNI_API_CACHE_TTL": "Seconds a cached response lives.",
    "KARNI_API_CACHE_ALIAS": "The Django cache alias responses are stored in.",
    "KARNI_ADMIN_AUTODISCOVER": "Register every unregistered model in the admin at startup (`karni.admin`).",
    "KARNI_ADMIN_EXCLUDE": "App labels or `app_label.ModelName` entries the admin leaves out.",
    "KARNI_IMPORT_INLINE_ROWS": "Files with at most this many rows [import](import-export.md) inside the request; larger ones run in Celery with progress.",
    "KARNI_IMPORT_MAX_ROWS": "An upload with more rows than this is refused (`E803`); split the file.",
    "KARNI_EXPORT_MAX_ROWS": "An [export](import-export.md) with more rows than this is refused (`E803`); narrow the filters.",
    "KARNI_MATRIX_EXCLUDE": "App labels or `app_label.ModelName` entries the [permission matrix](accounts.md#permission-matrix) leaves out (framework internals by default).",
    "KARNI_ADMIN_LIST_DISPLAY_MAX": "Columns a derived admin changelist shows at most.",
    "KARNI_ADMIN_LIST_FILTER_MAX": "Sidebar filters a derived admin shows at most.",
    "KARNI_ADMIN_SEARCH_MAX": "Fields a derived admin searches at most.",
    "KARNI_ADMIN_SITE": "Dotted path of the admin site models are registered on.",
    "KARNI_ADMIN_LOGO": 'Logo for the admin header and login: `karni` for Karni\'s mark, or `{"light": <static path>, "dark": ..., "icon": ...}`; unset leaves the text header. See [admin](admin.md#theming).',
    "KARNI_ADMIN_BASE": "Dotted path of the `ModelAdmin` every derived admin is built on.",
    "KARNI_ADMIN_PATH": "URL path the scaffold mounts the Django admin at (trailing slash); set it to something unguessable in production.",
    "KARNI_HEALTH_CHECKS": "Dotted paths of the checks `/health/ready/` runs (database, cache, Celery by default).",
    "KARNI_HEALTH_CELERY_TIMEOUT": "Seconds the readiness check waits for a Celery worker to answer.",
    "KARNI_THUMBNAILER": "Dotted path of the function `karni.storage.thumbnails` renders thumbnails with.",
    "KARNI_VALIDATE": "Validate the merged settings at startup (`karni.conf.validation`); `False` skips it.",
    "KARNI_EVENTS_AUTODISCOVER": "Import every app's `events.py` and `listeners.py` at startup.",
    "KARNI_SCHEDULES_AUTODISCOVER": "Import every app's `schedules.py` at startup.",
    "KARNI_ARCHITECTURE": "Configuration of the architecture rules: `skip_apps`, `sql_allowed`, `http_allowed`, `dup`. See [enforcement](enforcement.md).",
    "KARNI_SCOPES": "The active model scopes in pipeline order; unset runs every registered scope. See [models](models.md#scopes-the-filters-every-default-manager-applies).",
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
    name: str
    section: str
    default: str
    env: str | None
    description: str


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
    return re.sub(r",\s*([}\]])", r"\1", text)


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


def render(found: list[Setting] | None = None) -> str:
    rows = found if found is not None else settings()
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
        "never overwritten. This page lists the `KARNI_*` settings; the Django and",
        "DRF settings Karni derives are documented where the feature is.",
        "",
        "| Setting | Env | Default | What it does |",
        "|---|---|---|---|",
    ]
    section = None
    for row in rows:
        if row.section != section:
            section = row.section
            out.append(f"| **{section}** | | | |")
        env = f"`{row.env}`" if row.env else "—"
        default = f"`{row.default}`" if row.default and row.default != "—" else "—"
        out.append(f"| `{row.name}` | {env} | {default} | {row.description} |")
    out += [
        "",
        "Settings listed as computed derive from others; the defaults of env-backed",
        "settings are what an absent variable yields. `KARNI_VALIDATE` checks the merged",
        "values at startup and reports every bad one at once (error `E504`).",
        "",
        "Modules add their own settings through the `karni.settings` entry point and",
        "document them in their README; karni-payments' are listed above because the",
        "reference app installs it.",
        "",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    print(render(), end="")

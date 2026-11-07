# karni

The Python core of Karni: settings in one call, models, an API with access rules, an admin that registers itself, accounts and test helpers.

[![PyPI](https://img.shields.io/pypi/v/karni)](https://pypi.org/project/karni/) [![Python versions](https://img.shields.io/pypi/pyversions/karni)](https://pypi.org/project/karni/) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/)

Karni is a Django + React framework for building with coding agents. This package is its Django side: the code every Django + DRF + Celery project repeats, kept in a package you upgrade. [`@karni/ui`](https://www.npmjs.com/package/@karni/ui) is the React side, and [`karni-cli`](https://pypi.org/project/karni-cli/) is the `karni` command that scaffolds and builds projects.

## Install

```bash
pip install karni            # core
pip install 'karni[s3]'      # + S3-compatible storage (django-storages, boto3)
pip install 'karni[images]'  # + thumbnailing (Pillow)
pip install 'karni[sentry]'  # + Sentry (sentry-sdk)
pip install 'karni[social]'  # + social login (django-allauth)
pip install 'karni[social-token]'  # + sign-in with a Google, Microsoft or Apple ID token (experimental)
pip install 'karni[2fa]'     # + TOTP two-factor auth (django-otp)
```

A new project is quickest with the `karni` command: `pip install karni-cli`, then `karni new "Corner Shop" --recipe shop` ([quickstart](https://cbsshekhawat18-lab.github.io/karni/quickstart/)).

## A model and its API

```python
# events/models.py
from django.db import models
from karni.models import BaseModel

class Venue(BaseModel):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)

# events/viewsets.py
from karni.api import Access, BaseViewSet, HasRole, Public
from events.models import Venue

class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=HasRole("organizer", "staff"))
```

In a project from `karni new`, these two classes are the REST resource at `/api/venues/` with filters, search, pagination and `?expand=`, its OpenAPI schema, its admin screen, and the permission check on every query.

## Main features

- **Settings in one call.** `karni_settings(globals())` assembles the settings every project repeats, from the environment, and validates them at startup ([settings](https://cbsshekhawat18-lab.github.io/karni/settings/)).
- **Models.** `BaseModel` gives a UUID key, timestamps, soft delete and audit fields, and `karni.fields` gives typed fields the database enforces ([models](https://cbsshekhawat18-lab.github.io/karni/models/), [fields](https://cbsshekhawat18-lab.github.io/karni/fields/)).
- **The API.** `BaseViewSet` needs an `access` rule and derives the serializer, filters, search, pagination, `?expand=` and an N+1-free query plan ([API](https://cbsshekhawat18-lab.github.io/karni/api/)).
- **The admin.** `karni.admin` registers every model in a django-unfold admin with derived columns, filters and search, with no `admin.py` ([admin](https://cbsshekhawat18-lab.github.io/karni/admin/)).
- **Accounts.** `karni.accounts` has an email-based swappable user, JWT or session auth endpoints, the email flows, roles, per-user grants, TOTP two-factor and social login ([accounts](https://cbsshekhawat18-lab.github.io/karni/accounts/)).
- **History, events and schedules.** Field-level change history, listeners queued to Celery, and periodic tasks ([change history](https://cbsshekhawat18-lab.github.io/karni/change-history/), [events](https://cbsshekhawat18-lab.github.io/karni/events/), [scheduling](https://cbsshekhawat18-lab.github.io/karni/scheduling/)).
- **Tests in one line.** `karni.testing` has `assert_crud`, `assert_isolated`, `client_as` and query budgets ([testing](https://cbsshekhawat18-lab.github.io/karni/testing/)).

## A whole settings.py

```python
from karni.conf import karni_settings

karni_settings(globals())

# Project-specific settings below. Anything defined here wins.
INSTALLED_APPS += [
    # "myapp",
]
```

That call configures: `INSTALLED_APPS`, middleware, Postgres from
`DATABASE_URL`, Redis cache, DRF (pagination, filter backends, throttling,
drf-spectacular schema), Celery (+ django-celery-beat, django-celery-results),
file storage (local or S3-compatible), structlog logging (console in dev,
JSON in prod), security headers, CORS, and optional Sentry. At startup the
merged settings are validated by a Pydantic model and every bad value is
reported at once (`KARNI_VALIDATE = False` skips this).

## Overriding defaults

`karni_settings()` uses **setdefault semantics**: it never overwrites a name
you already defined. Three layers, strongest first:

1. **Assign after the call.** This always wins:
   `REST_FRAMEWORK["PAGE_SIZE"] = 20`
2. **Define before the call.** Karni never touches it. For `INSTALLED_APPS` and
   `MIDDLEWARE`, Karni appends its missing entries after yours instead of
   replacing the list.
3. **Keyword overrides.** `karni_settings(globals(), CELERY_TASK_TIME_LIMIT=60)`
   replaces the Karni default (whole-value replacement) but still yields to
   names defined in the module.

Most defaults also read environment variables (via django-environ), so the
same image runs in dev and prod with only a `.env` change.

## Profiles

`DJANGO_ENV=dev` (default) or `DJANGO_ENV=prod`, or force one with
`karni_settings(globals(), env_name="prod")`.

| | dev | prod |
|---|---|---|
| `DEBUG` | `True` | `False` |
| `ALLOWED_HOSTS` | `["*"]` | required, from env |
| `SECRET_KEY` | insecure default allowed | required, validated |
| Logging | colorized console (structlog) | JSON lines (structlog) |
| CORS | allow all origins | `CORS_ALLOWED_ORIGINS` only |
| Security headers | off | HSTS, SSL redirect, secure cookies, nosniff, `X-Frame-Options: DENY` |

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DJANGO_ENV` | `dev` | settings profile: `dev` or `prod` |
| `SECRET_KEY` | insecure dev key | **required in prod** (validation fails otherwise) |
| `DEBUG` | dev `True` / prod `False` | debug mode |
| `ALLOWED_HOSTS` | dev `*` / prod empty | comma-separated, **required in prod** |
| `DATABASE_URL` | `postgres://karni:karni@db:5432/karni` | database DSN |
| `REDIS_URL` | `redis://redis:6379/0` | cache + Celery broker |
| `CORS_ALLOWED_ORIGINS` | empty | comma-separated origins |
| `KARNI_PAGE_SIZE` | `50` | DRF default page size |
| `THROTTLE_ANON` / `THROTTLE_USER` | `100/min` / `1000/min` | DRF throttle rates |
| `PROJECT_NAME` | `karni-project` | API title, Celery app name |
| `KARNI_STORAGE` | `local` | `local` or `s3` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME` | empty | S3-compatible storage (MinIO/R2 via endpoint URL) |
| `SENTRY_DSN` | empty | Sentry disabled when empty |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0` | Sentry tracing sample rate |
| `MEDIA_ROOT` / `STATIC_ROOT` | `/data/media` / `/data/static` | file roots |

## Celery

```python
# config/celery.py
from karni.celery import create_celery_app

app = create_celery_app()
```

Broker, django-db results, database beat scheduler and task autodiscovery are
configured from the `CELERY_*` settings that `karni_settings()` provided.
Periodic tasks declared with `karni.schedule.every()` / `cron()` in
`<app>/schedules.py` are merged into the beat schedule
([docs/scheduling.md](https://cbsshekhawat18-lab.github.io/karni/scheduling/)). Model lifecycle listeners
live in `<app>/listeners.py` ([docs/events.md](https://cbsshekhawat18-lab.github.io/karni/events/)).
`manage.py karni_routes` and `manage.py karni_schedules` list every URL and
every schedule (`--json` for agents).

## Health checks

```python
# config/urls.py
path("health/", include("karni.health.urls")),
```

`/health/` is a no-I/O liveness probe. `/health/ready/` runs the checks in
`KARNI_HEALTH_CHECKS` (Postgres, Redis and Celery by default, as a list of
dotted paths you can extend or replace) and returns 200 or 503 with per-check detail.

## Storage & thumbnails

`KARNI_STORAGE=s3` switches the default storage to
`karni.storage.S3Storage` (S3-compatible, endpoint-aware). Anything else uses
local `FileSystemStorage`. `karni.storage.thumbnails.make_thumbnail()`
produces aspect-preserving thumbnails. To swap the implementation, set the
`KARNI_THUMBNAILER` dotted-path setting.

## Development

```bash
cd packages/karni
pip install -e . --group dev
pytest
ruff check .
```

## Links

- Documentation: <https://cbsshekhawat18-lab.github.io/karni/>
- Every feature, with its status: <https://cbsshekhawat18-lab.github.io/karni/features/>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. karni is released with every other Karni package, at one version.

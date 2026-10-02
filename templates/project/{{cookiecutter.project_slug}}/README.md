# {{ cookiecutter.project_name }}

A [Karni](https://github.com/karni) project: batteries-included Django + DRF +
Celery, configured almost entirely by `karni_settings(globals())` in
`config/settings.py`. Every Karni default can be overridden from that file —
anything you assign after the call wins.

## Quickstart

```sh
cp .env.example .env
docker compose up --build
```

This boots:

| Service    | What                                            | Where                  |
| ---------- | ----------------------------------------------- | ---------------------- |
| `django`   | migrations, then Django dev server              | http://localhost:8000  |
| `db`       | postgres:16                                     | internal (`db:5432`)   |
| `redis`    | redis:7 (Celery broker + cache)                 | internal (`redis:6379`)|
| `worker`   | Celery worker                                   | —                      |
| `beat`     | Celery beat (django-celery-beat DB scheduler)   | —                      |
| `frontend` | Vite dev server (React + TS), proxies `/api` and `/health` to django | http://localhost:5173 |

Verify the stack (Postgres, Redis and Celery all checked):

```sh
curl http://localhost:8000/health/ready/
# {"status": "ok", "checks": {"database": ..., "cache": ..., "celery": ...}}
```

Other endpoints: liveness at `/health/`, admin at `/admin/`, OpenAPI schema at
`/api/schema/`, Swagger UI at `/api/docs/`.

## Using a local karni checkout

Until karni is published to PyPI, vendor a checkout into the project and point
the `KARNI_SRC` build arg at it (docker-compose reads it from `.env`):

```sh
cp -r /path/to/Karni/packages/karni ./.karni-src
echo "KARNI_SRC=.karni-src" >> .env   # or edit the existing line
docker compose build
```

`KARNI_SRC` must be a path inside this project (the Docker build context).
The vendored copy is installed before the PyPI dependencies, so it takes
precedence.

## Day-to-day

```sh
docker compose run --rm django python manage.py createsuperuser
docker compose run --rm django python manage.py startapp myapp
docker compose run --rm django python manage.py makemigrations
```

Add new apps to `INSTALLED_APPS` in `config/settings.py`; override any Django,
DRF, Celery or Karni setting in the same file, below the `karni_settings()`
call.

## AI coding agents

`karni new` generated thin agent adapters — `AGENTS.md`, `CLAUDE.md`,
`.cursor/rules/karni.mdc`, `.windsurf/rules/karni.md`,
`.github/copilot-instructions.md`, `.clinerules/karni.md`, `CONVENTIONS.md`,
`.junie/AGENTS.md` and slash commands. They all say the same thing: run
`karni context` and `karni rules` first. Do not edit them; put project rules
in `karni.rules.py` and run `karni rules sync` (`make check` fails when they
are stale). `karni mcp` serves the same surface over MCP.

## Production

The `prod` Dockerfile target builds a slim, non-root image that runs
`gunicorn config.asgi:application` with uvicorn workers and collects static
files to `/data/static` at build time:

```sh
docker build --target prod -t {{ cookiecutter.project_slug }}:latest .
```

Run it with `DJANGO_ENV=prod`, a real `SECRET_KEY` and `ALLOWED_HOSTS` —
Karni validates the configuration at startup and fails loudly on anything
insecure or missing. Put Caddy in front using the provided `Caddyfile`: it
provisions TLS for `$DOMAIN` automatically, serves `/static/*` and `/media/*`
from `/data` (share the `/data` volume between the django container and
Caddy), and reverse-proxies everything else to `django:8000`. For the
frontend, `npm run build` in `frontend/` produces static assets you can serve
from Caddy or any CDN.

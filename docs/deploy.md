---
description: "Put a Karni project in production on one server with Docker Compose: the production stack every new project gets, DNS, automatic TLS through Caddy, the .env.prod checklist that karni check --deploy enforces when each container starts, the first start, updates without failed requests, rollback, logs, and backups with a tested restore."
---

# Deploying to a server

Every new Karni project has a production stack next to its development one.
`karni new` writes three files for it, and `karni make deploy compose` writes
them in an existing project:

| File | What it is |
|---|---|
| `docker-compose.prod.yml` | The services below, with health checks, restart policies, memory limits, log rotation and named volumes. No source code is mounted from the host. |
| `Caddyfile` | The web front: TLS, static and media files, the staff app, and the proxy to Django. |
| `.env.prod.example` | Every production value. Copy it to `.env.prod` on the server and fill it in. |

The images come from the project's `Dockerfile` (targets `prod` and
`backup`). The logic they run is in Karni (`karni.deploy`), so `karni upgrade`
fixes it for every project. The three files are yours to edit.

With Docker on the server, one command starts everything:

```sh
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

The rest of this page goes through a first deployment step by step, then
updates, rollback, logs, backups and restore, and then health checks, Celery
and beat, static and media files, API versions for mobile clients and
scaling.

## What runs

| Service | What it does | Health check |
|---|---|---|
| `release` | Runs once per start, before the others: the deploy checks, `migrate`, `collectstatic`, then `karni_publish_web`, which copies the Caddyfile, the built staff app and the security headers into the shared volume. If it fails, nothing else starts. | none: the others wait for it to exit with 0 |
| `django` | gunicorn with uvicorn workers (`WEB_CONCURRENCY`, default 2). It serves the API, the admin, `/healthz`, `/readyz`, `/health/` and a public site app. | `/readyz`, asked as Caddy asks it ([health checks](#12-health-checks)) |
| `worker` | The Celery worker (`KARNI_WORKER_CONCURRENCY`, default 2). | `celery inspect ping` |
| `beat` | Celery beat. Run exactly one. | its process has passed the deploy checks |
| `caddy` | TLS for `DOMAIN`, `/static/` and `/media/` from the shared volume, the staff app, and everything else proxied to `django`. Publishes ports 80 and 443. | its admin API |
| `db` | PostgreSQL (`POSTGRES_VERSION`, default 16). Not reachable from outside the stack. | `pg_isready` |
| `redis` | The Celery broker and the cache. Under memory pressure it drops cache keys, never a queued task. | `redis-cli ping` |
| `backup` | Database and media backups on a schedule, with retention. | the last backup did not fail |

Every container built from the `prod` image starts through
`python -m karni.deploy.entrypoint`, which runs `karni check --deploy` first
(Django's `check --deploy` and Karni's [deploy checks](security.md#deploy-checks)).
When a check fails, the container prints each finding with its code and fix,
then `E520`, and exits without starting its command. So a missing
`SECRET_KEY`, `DEBUG` left on or the admin at `/admin/` stops the deployment
instead of reaching users.

For an emergency start with a failing check, set `KARNI_SKIP_DEPLOY_CHECK=1`
in `.env.prod`. Every container then logs, on every start, that the checks did
not run. Remove it as soon as the values are fixed.

### Choices

`karni make deploy compose` takes flags for what differs between projects.
Run it again with `--force` to rewrite the files:

| Flag | Effect |
|---|---|
| `--app-path /staff/` | Serve the staff app under another path (default `/app/`). `/` serves it at the root of the site, for a project without a public site. |
| `--app-domain app.example.com` | Serve the staff app on its own host, with the API on the same origin. |
| `--no-app` | Serve no staff app. |
| `--no-celery` | No worker and no beat. `.env.prod.example` then sets `KARNI_HEALTH_CHECKS` without the Celery check. |
| `--no-db`, `--no-redis` | Use a managed PostgreSQL or Redis: set `DATABASE_URL` or `REDIS_URL` to it. |
| `--no-backups` | No backup service. |
| `--domain example.com` | The host written into `.env.prod.example`. |

Hosts, ports, image names and sizes are variables in `.env.prod`, listed in
`.env.prod.example`.

### The staff app

The staff app in `frontend/` is built into the production image by the
Dockerfile's `staff-app` stage: `npm ci` (or `npm install` without a lock
file), then `npm run build` with Vite's base set to the app's path
(`KARNI_APP_PATH`, `/app/` by default). The router in `src/routes.tsx` takes
the same base, so links and reloads work under it.

The release step copies the build into the shared volume, and Caddy serves it:
`/app/` answers `index.html`, any deeper path of the app (a reload, a shared
link) answers `index.html` too, and the hashed files under `/app/assets/` are
cached for a year. The app calls the API at `/api/` on the same origin, so no
CORS setting is needed and session cookies work.

Caddy sends the security headers Django sends (the content security policy,
HSTS and the others) on the app and on static files. `karni_publish_web` writes
them from the project's settings on every release, so a source added to
`KARNI_CSP` reaches the app as well. Files of the previous build stay for seven
days, so a browser that still holds the previous `index.html` keeps working
during an update.

A project without `frontend/package.json` gets no staff app, and nothing else
changes.

## 1. A server

One small server is enough to start: 2 GB of memory, 1 or 2 CPUs and 20 GB of
disk, with a current Ubuntu LTS or Debian. Install Docker Engine and its
Compose plugin [as Docker documents for your distribution](https://docs.docker.com/engine/install/),
and add your user to the `docker` group.

Open ports 22, 80 and 443 (TCP) in the firewall, and 443 over UDP for HTTP/3.
Caddy is the only service that publishes ports.

Building the image needs about 1.5 GB of memory for the staff app's build. On
a 1 GB server, add swap or build the images elsewhere and push them to a
registry (set `KARNI_IMAGE` to the registry's name).

## 2. DNS

Create an `A` record (and an `AAAA` record for IPv6) for the site's host,
pointing at the server's address. With `--app-domain`, create one for the
app's host too. Check that it resolves before the first start:

```sh
dig +short example.com
```

## 3. TLS

Caddy gets the certificate by itself on the first start, once DNS points at
the server and ports 80 and 443 reach it, and renews it before it expires.
Plain-http requests are redirected to https. The certificates live in the
`caddy_data` volume: keep it, since certificate authorities limit how often a
host may ask for a new one. To receive expiry notices, uncomment the `email`
line at the top of the `Caddyfile`.

The production profile sends HSTS for one year with `preload`, which browsers
remember. While you try a new domain, set `SECURE_HSTS_SECONDS=3600` in
`.env.prod`, and remove it once https works.

## 4. The code and `.env.prod`

```sh
git clone https://git.example.com/you/your-project.git
cd your-project
cp .env.prod.example .env.prod
chmod 600 .env.prod
```

Fill in every empty value. The file shows a command that generates each
secret:

- `SECRET_KEY`: 50 or more random characters.
- `KARNI_ADMIN_PATH`: a path nobody guesses, with a trailing slash, for
  example `staff-7f3a9c2e/`. The admin answers there and `/admin/` answers 404.
- `POSTGRES_PASSWORD`, and the same password in `DATABASE_URL`. Use letters
  and digits: they need no escaping in the URL.
- `DOMAIN`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `KARNI_FRONTEND_URL`,
  already set from the domain `karni new` was given.

Then uncomment the email lines and fill them in. Password resets, account
emails and the notifications of a site's forms go through them, and the
containers refuse to start without them (`karni.W520`):

- `EMAIL_URL`: the mail server, host, port, user and password in one URL,
  `smtp+tls://user:password@smtp.example.com:587` (`smtps://` for SSL on port
  465). Write an `@` in the user or password as `%40`.
- `DEFAULT_FROM_EMAIL`: the sender, an address of the site's domain such as
  `noreply@example.com`. The mail server must accept it as a sender.

A project that sends no email at all adds `"karni.W520"` to
`SILENCED_SYSTEM_CHECKS` in `config/settings.py` instead.

Copy any other setting the project changed in `.env` (registration, roles,
`KARNI_CSP` for a font host, `KARNI_PHONE_COUNTRY_CODE`, Sentry). Avoid `$` in values: Compose reads
it as a variable. Never commit `.env.prod`. The scaffold's `.gitignore` and
`.dockerignore` list it, so it is neither committed nor copied into the image.

Check the file before starting:

```sh
docker compose -f docker-compose.prod.yml --env-file .env.prod config --quiet
```

The commands below are long, so define a short name for them in the shell on
the server:

```sh
prod() { docker compose -f docker-compose.prod.yml --env-file .env.prod "$@"; }
```

### The variables that matter

`.env.prod.example` lists every value. These are the ones that change how the
site behaves, grouped by what they do:

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | none | Signs sessions and tokens. 50 or more random characters. Changing it signs everyone out. |
| `DJANGO_ENV`, `DEBUG` | `prod`, off | The production profile. `karni check --deploy` refuses `DEBUG` on. |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | the domain | The hosts Django answers and the origins whose forms it trusts. |
| `KARNI_ADMIN_PATH` | none | Where the admin is. |
| `DATABASE_URL`, `REDIS_URL` | the stack's | Where PostgreSQL and Redis are. A managed service is a different URL. |
| `WEB_CONCURRENCY`, `KARNI_WORKER_CONCURRENCY` | `2`, `2` | Gunicorn workers and Celery processes ([scaling](#16-scaling)). |
| `KARNI_READYZ_CHECKS`, `KARNI_HEALTH_CHECKS`, `KARNI_HEALTH_TIMEOUT` | database, cache, broker, plus Celery, 3 seconds | What `/readyz` and `/health/ready/` check and how long each check may take ([health checks](#12-health-checks)). |
| `KARNI_LOG_QUIET_PATHS` | the probe paths | Paths whose successful requests the request log skips. |
| `KARNI_API_VERSION`, `KARNI_API_VERSIONS`, `KARNI_API_UNVERSIONED` | unversioned | The API's version prefix and deprecations ([API versions](#15-api-versions-for-mobile-clients)). |
| `KARNI_STORAGE`, `MEDIA_ROOT`, `STATIC_ROOT` | local, `/data/...` | Where uploads and static files live ([files](#14-static-and-media-files)). |
| `KARNI_BACKUP_*`, `POSTGRES_VERSION` | see [backups](#10-backups) | Backup retention, interval and the bucket. |
| `SENTRY_DSN` | empty | Error reports. |

A variable in `.env.prod` reaches the containers through Compose's `env_file`.
A JSON value is written in single quotes, such as
`KARNI_API_VERSIONS='{"v0": {"deprecated": true}}'`.

## 5. First start

```sh
prod up -d --build
prod ps
```

The build takes a few minutes the first time. Then `release` runs and exits,
and the other services start. Within a minute or two `prod ps` shows each of
them `healthy`. Check the whole stack, including the database, the cache and
the Celery broker:

```sh
curl https://example.com/readyz
```

`/health/ready/` also needs a Celery worker to answer. Ask it to know the
worker runs ([health checks](#12-health-checks)).

If a service does not become healthy, its log says why:

```sh
prod logs release
prod logs django
```

A failing deploy check shows its code (`karni.W511` for a weak key, for
example), and `karni explain W511` says what the value must be.

## 6. The first superuser

```sh
prod exec django python manage.py createsuperuser
```

Sign in at `https://example.com/<KARNI_ADMIN_PATH>`. The staff app is at
`https://example.com/app/`.

## 7. Updates

An update builds the new image while the old containers keep serving, applies
the migrations, then replaces the containers.

```sh
git pull
prod exec backup karni-backup run          # a backup first, for a rollback
prod build
prod run --rm release                      # deploy checks, migrations, static and web files
prod up -d --no-build --no-deps django worker beat backup
```

`up` stops each old container and starts the new one. While `django`
restarts, Caddy holds incoming requests and retries for up to 30 seconds, so
they are answered a few seconds late instead of failing. A Celery task that
is running gets 60 seconds to finish, and queued tasks wait in Redis for the
new worker.

To have no pause at all, start the new `django` container next to the old one,
wait until it is healthy, then stop the old one. Caddy sends requests to both
while both run:

```sh
old=$(prod ps -q django)
prod up -d --no-build --no-deps --no-recreate --scale django=2 django
new=$(prod ps -q django | grep -v "$old")
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$new")" = healthy ]; do sleep 2; done
docker stop "$old" && docker rm "$old"
```

When the `Caddyfile` changed, reload Caddy after the release step. The reload
does not drop connections:

```sh
prod exec caddy caddy reload --config /srv/data/web/Caddyfile
```

To keep each release's image for a rollback, tag it before the next build:

```sh
tag=$(git rev-parse --short HEAD)
docker tag your_project:latest "your_project:$tag"
docker tag your_project-backup:latest "your_project-backup:$tag"
```

(The image is named after the project, `KARNI_IMAGE` in `.env.prod`.)

### Migrations on deploy

Migrations run in the `release` step, once per deployment, before any new
container serves a request. `django`, `worker` and `beat` never migrate, so
two replicas cannot race, and a migration that fails stops the deployment with
the old containers still serving. Run them by hand with `prod run --rm release`
(the whole step) or `prod exec django python manage.py migrate --check` to
see whether any are pending. Take a backup first when a migration changes or
drops data: `prod exec backup karni-backup run`.

### Migrations that the old code cannot run with

Between the release step and the restart, the old code runs against the new
schema. Adding a table, or a column that is nullable or has a default, is
safe. Removing or renaming a column, or making one required, breaks the old
code during that window. Split such a change over two releases:

1. Add the new column or table, nullable. The code writes both the old and
   the new place and reads the new one with a fallback. A data migration
   copies the old values.
2. In the next release, once no running code reads the old column, remove it.

When a change cannot be split, take a short maintenance window instead: stop
the services that use the database, run the release step, start them again.
Requests get an error for that minute.

```sh
prod stop django worker beat
prod run --rm release
prod up -d --no-build django worker beat
```

## 8. Rollback

When the release had no migration, or only migrations the previous code can
run with, start the previous image:

```sh
docker tag your_project:<previous tag> your_project:latest
docker tag your_project-backup:<previous tag> your_project-backup:latest
prod run --rm release
prod up -d --no-build --no-deps django worker beat backup
```

The release step also restores the previous Caddyfile and staff app, so
reload Caddy when the Caddyfile differs.

When a migration must be undone, reverse it with the new image first, then
start the previous one:

```sh
prod run --rm django python manage.py migrate <app> <previous migration>
```

When a migration cannot be reversed, or data was lost, restore the backup
taken before the update (below).

## 9. Logs

```sh
prod logs -f django worker            # follow
prod logs --since 1h caddy            # the last hour
prod ps                               # state and health of each service
```

Django writes one JSON object per line in production, with the request id of
each request, so a log tool can read it. Each container's log is rotated at
10 MB and five files are kept. Caddy logs its own errors and certificate
renewals. To log every request, add a `log` directive to the `Caddyfile`.
Errors reach Sentry when `SENTRY_DSN` is set (`karni[sentry]`).

## 10. Backups

The `backup` service writes a backup when one is due: at start when the
newest one is older than `KARNI_BACKUP_INTERVAL_HOURS` (default 24), then
every interval. It keeps the newest `KARNI_BACKUP_KEEP` (default 7). A backup
is a folder named by its UTC time, holding the database (`pg_dump`, custom
format), the media files and a manifest. It is written under a temporary
name and renamed when complete, so a backup that failed half way never
counts.

```sh
prod exec backup karni-backup run     # one now
prod exec backup karni-backup list    # newest first
```

When a backup fails, the service logs `E521` with the step that failed, and
its health check turns unhealthy until a backup succeeds.

Backups in the `backups` volume do not survive the loss of the server. Set
`KARNI_BACKUP_S3_BUCKET` (with `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
and `AWS_S3_ENDPOINT_URL` for a service other than AWS) and each backup is
also uploaded there, with the same retention. Otherwise, copy the volume's
contents off the server on a schedule.

| Variable | Default | Meaning |
|---|---|---|
| `KARNI_BACKUP_KEEP` | `7` | backups kept, locally and in the bucket |
| `KARNI_BACKUP_INTERVAL_HOURS` | `24` | hours between backups |
| `KARNI_BACKUP_DIR` | `/backups` | where backups are written in the container |
| `KARNI_BACKUP_MEDIA_ROOT` | `MEDIA_ROOT` | the media folder to archive (empty: none) |
| `KARNI_BACKUP_S3_BUCKET` | none | also upload each backup to this bucket |
| `KARNI_BACKUP_S3_PREFIX` | `backups/` | the key prefix in the bucket |
| `POSTGRES_VERSION` | `16` | the database's major version, which the backup image's `pg_dump` matches |

The backup service uses the PostgreSQL client tools of `POSTGRES_VERSION`.
Tools of a newer major version write dumps an older server may refuse to
restore, so keep it equal to the database's version, a managed one included.

The tool is a standard-library Python file of Karni, so another scheduler can
run it too: `python -m karni.deploy.backup run` wherever `pg_dump` is
installed.

## 11. Restore

Restore into a second database first, and compare it with the live one. The
row counts match when nothing was written since the backup:

```sh
prod exec backup sh -c 'karni-backup restore latest --create --database-url "${DATABASE_URL%/*}/restore_check"'
prod exec backup sh -c 'karni-backup counts --database-url "$DATABASE_URL" --against "${DATABASE_URL%/*}/restore_check"'
```

`restore` runs in one transaction, so a restore that fails changes nothing.
`latest` is the newest backup, or name one from `karni-backup list`. When the
backup is only in the bucket, it is downloaded first.

To replace the live database and media with a backup, stop what writes to
them, restore with `--clean`, then start again:

```sh
prod stop django worker beat
prod exec backup karni-backup restore latest --clean --media-root /data/media
prod run --rm release
prod up -d --no-build django worker beat
```

Without `--database-url`, `restore --clean` restores over `DATABASE_URL`.
Restored media files are given to the owner of the media folder, so uploads
keep working. Drop the check database when you no longer need it:

```sh
prod exec db sh -c 'dropdb -U "$POSTGRES_USER" restore_check'
```

## 12. Health checks

Karni answers four URLs. None needs a login, none is cached, and none is
asked of the terms gate, so a proxy, an orchestrator or a monitor can call
them at any time. The request log skips the successful ones
(`KARNI_LOG_QUIET_PATHS`), so a probe every few seconds does not fill it.

| URL | Means | Touches |
|---|---|---|
| `/healthz` | The process answers. Liveness: restart the container when this fails. | nothing |
| `/readyz` | The process can serve: the database, the cache and the Celery broker respond. Readiness: send no traffic when this fails. | database, cache, broker |
| `/health/` | The older liveness URL. Same answer as `/healthz`. | nothing |
| `/health/ready/` | The older readiness URL, which also needs a Celery worker to answer. | database, cache, a worker |

```sh
curl -i https://example.com/readyz
```

```json
{"status": "ok", "failing": [],
 "checks": {"database": {"ok": true, "detail": "database responding"},
            "cache": {"ok": true, "detail": "cache responding"},
            "broker": {"ok": true, "detail": "broker responding"}}}
```

When a check fails the status is 503, `status` is `fail` and `failing` names
it, such as `"failing": ["cache"]`, with the error in that check's `detail`.
Each check gets `KARNI_HEALTH_TIMEOUT` seconds (default 3). One that does not
answer in time fails with `no answer within 3s`, so a database that accepts the
connection and then stalls cannot hold the probe.

`/readyz` leaves the Celery workers out on purpose. A web container is ready
when it can enqueue a task, whether or not a worker is up this second. Ask
`/health/ready/` when you want to know a worker answers, as the CI job does.

The checks are settings. `KARNI_READYZ_CHECKS` and `KARNI_HEALTH_CHECKS` list
dotted paths to functions that return `(ok, detail)`, comma-separated in the
environment, so a project adds its own check (an object store, a mail relay)
or removes one:

```sh
KARNI_READYZ_CHECKS=karni.health.checks.check_database,karni.health.checks.check_cache
```

The compose files' health check for `django` asks `/readyz`, and Caddy
forwards `/healthz` and `/readyz` so an outside monitor can ask too. A project
created before these URLs keeps asking `/health/`. Add them with
`from karni.health.probe_urls import urlpatterns as probe_urls` and
`*probe_urls` in `config/urls.py`, then run `karni make deploy compose --force`.

## 13. Celery and beat

`worker` runs the Celery worker with `KARNI_WORKER_CONCURRENCY` processes and
`beat` runs the scheduler. Both take their broker from `REDIS_URL`.

- Run exactly one `beat`. Two would enqueue every scheduled task twice. The
  schedule is in the database (`django-celery-beat`), so a restart loses
  nothing.
- A worker finishes the task it is running for up to 60 seconds when it is
  stopped. Queued tasks wait in Redis for the new worker. Redis is set to drop
  cache keys under memory pressure and never a queued task.
- A task that takes longer than the time limits (`CELERY_TASK_TIME_LIMIT`, 300
  seconds, and `CELERY_TASK_SOFT_TIME_LIMIT`, 240) is stopped. Raise them for
  a long job, or split it.
- Without tasks to run, `karni make deploy compose --no-celery` leaves both
  out, and `/health/ready/` stops asking for a worker.
- `/readyz` fails when the broker does not answer. A worker that is down shows
  in `prod ps` (its health check is `celery inspect ping`) and in
  `/health/ready/`.

## 14. Static and media files

The `release` step runs `collectstatic` into the `app_data` volume and
`karni_publish_web` copies the staff app next to it. Caddy reads the volume
and serves `/static/`, `/media/` and the staff app with long cache lifetimes
on the hashed files, so Django never serves a file in production.

- Static files are written on every release. Nothing to back up.
- Uploads are written by Django to `MEDIA_ROOT` (`/data/media`) in the same
  volume, and Caddy serves them from there. The backup service archives that
  folder with the database ([backups](#10-backups)).
- On more than one server, or to keep uploads out of a volume, set
  `KARNI_STORAGE=s3` with the bucket's settings. Django then writes to the
  bucket and the media folder stays empty. See [settings](settings.md).
- The volume is a Docker named volume. `prod down -v` deletes it, so never run
  that on a server that matters.

## 15. API versions for mobile clients

A browser app is replaced on the next page load. A mobile app is not: the
build a user installed last year still calls your API. A version prefix lets
the API change for new builds while old ones keep a URL that does not move.
It is off until you set it, and an unversioned project is unchanged.
Experimental, see [API versions](api.md#api-versions) for the whole
reference.

```sh
KARNI_API_VERSION=v1                      # /api/v1/products/
KARNI_API_UNVERSIONED=keep                # /api/products/ still works
KARNI_API_VERSIONS='{"v0": {"deprecated": "2026-06-01", "sunset": "2027-01-31", "notes": "https://example.com/api-v0-to-v1"}}'
```

A response from `/api/v0/` then carries these headers:

```text
Deprecation: @1780272000
Sunset: Sun, 31 Jan 2027 00:00:00 GMT
Link: <https://example.com/api-v0-to-v1>; rel="deprecation"; type="text/html"
```

Ship a new version in three steps: add `v2` and make it current, mark `v1`
deprecated with a sunset date, and read the logs for `/api/v1/` until no
client calls it. Then remove `v1` from `KARNI_API_VERSIONS`. `karni check`
warns (`karni.W660`) about a version still mounted after its sunset date.
`/api/auth/`, `/api/schema/` and `/api/docs/` are not versioned.

Each version has its own OpenAPI document at `/api/<version>/schema/`, and
`karni types` writes a typed client for each into `frontend/src/api/<version>/`.
Hand a mobile team the document of the version they target.

## 16. Scaling

The stack is one server. Most of what limits it is memory, and each service
has a limit in `.env.prod` (`KARNI_DJANGO_MEMORY` and the others).

- **More requests:** raise `WEB_CONCURRENCY`, about two gunicorn workers per
  CPU core, and the memory limit with it. Each worker holds the application
  once. If that is not enough, start a second `django` container
  (`prod up -d --scale django=2`) and Caddy sends requests to both.
- **More background work:** raise `KARNI_WORKER_CONCURRENCY`, or run a second
  `worker` service on its own queue. Leave `beat` at one.
- **The database:** it is the first thing to outgrow the server. Move it to a
  managed PostgreSQL (`--no-db`, `DATABASE_URL` pointing at it, and
  `POSTGRES_VERSION` equal to its major version), which also gives you its
  backups and failover. Keep the `backup` service for a copy you control.
- **Redis:** one instance serves the cache and the queue. Point `REDIS_URL` at
  a managed Redis (`--no-redis`) when the server's memory is the limit.
- **Files:** past one server, use `KARNI_STORAGE=s3` so every container sees
  the same uploads.
- **Running more than one `django` container:** nothing is stored in the
  container, so any request can go to any of them. The cache, the sessions'
  throttle counters and the queue are in Redis, which all of them share.
- **Where to look first:** `karni queries` and the
  [performance](api.md#performance) section name the slow query, and
  `docker stats` shows which service is at its memory limit.

## An existing project

A project created before Karni 0.5.0 has a `Dockerfile` without the
`staff-app` and `backup` targets and without the deploy gate. Copy those parts
from a new project's `Dockerfile` (`karni new` in a scratch folder), add the
`basepath` line to `frontend/src/routes.tsx`, then write the stack:

```sh
karni make deploy compose --force
```

`--force` replaces an existing `Caddyfile`. The command stops with `C105`
and names the missing target when the `Dockerfile` lacks one.

## Before Karni is published

To build the images from a Karni checkout instead of the releases, copy the
packages into the project, which is the image's build context, and name them
in `.env.prod`:

```sh
cp -r /path/to/Karni/packages/karni .karni-src
mkdir -p .karni-ui
(cd /path/to/Karni/packages/karni-ui && npm ci && npm run build && npm pack --pack-destination "$OLDPWD/.karni-ui")
```

```sh
KARNI_SRC=.karni-src
KARNI_UI_TARBALL=.karni-ui/karni-ui-0.4.0.tgz
```

Karni's CI does exactly this in its "Production stack (compose, smoke)" job.
It creates a project with `karni new` (with a site, and one model with its
list page), builds both images, starts the stack with generated production
values and migrates. It seeds demo rows (`karni_seed`) and runs
`.github/ci/prod_smoke.py check`, which reads `/readyz` and `/healthz`, signs
in through the API, reads a list endpoint at `/api/` and at `/api/v1/`,
checks that a deprecated version sends its headers, opens a public page, the
admin login, a static file and the staff app, and checks the security headers.
Then one Playwright test (`.github/ci/prod_e2e/signin.spec.ts`) signs in to the
built staff app and sees a table of the seeded rows. The job ends with the
deploy gate and a backup restored into a second database. The smoke script
and the Playwright test run by hand against any running stack, `runserver`
included, as their files say.

# syntax=docker/dockerfile:1
# Multi-stage build for Medintel.
#
# Targets:
#   dev:    docker-compose.yml. Runserver-friendly, source bind-mounted over /app.
#   prod:   docker-compose.prod.yml's django, worker, beat and release services.
#           Slim and non-root: gunicorn with uvicorn workers, the built staff app
#           in frontend/dist, and `karni check --deploy` before every start.
#   backup: docker-compose.prod.yml's backup service: pg_dump of the database's
#           major version and Karni's backup tool (karni-backup).
#
# Build args (docker-compose.prod.yml passes them from .env.prod):
#   KARNI_SRC         path *inside this project* to a local karni checkout,
#                     installed before (and therefore instead of) the PyPI
#                     release. Until karni is published, vendor it (README.md).
#   KARNI_UI_TARBALL  path inside this project to a packed @karni/ui (npm pack),
#                     installed instead of frontend/package.json's spec. Needed
#                     when that spec is a local checkout ("file:..."), which is
#                     outside this build.
#   KARNI_APP_PATH    where the staff app is served (/app/), its Vite base.
#   POSTGRES_VERSION  the database's major version (16). pg_dump must match it.

ARG POSTGRES_VERSION=16

FROM python:3.12-slim AS base
# Uploads and static files live on the /data volume in every container (on the
# host they default to data/ under the project).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIA_ROOT=/data/media \
    STATIC_ROOT=/data/static
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

FROM base AS deps
WORKDIR /app
RUN uv venv /venv
ARG KARNI_SRC=""
# Copy the whole context so a vendored karni checkout (KARNI_SRC) is available.
COPY . /app/
# Installing KARNI_SRC first satisfies the "karni" requirement, so the
# pyproject install below skips resolving it from PyPI. The backup tool is one
# standard-library file of the installed karni, copied out for the backup target.
RUN if [ -n "${KARNI_SRC}" ]; then \
        uv pip install --python /venv/bin/python "./${KARNI_SRC}"; \
    fi \
    && uv pip install --python /venv/bin/python -r pyproject.toml \
    && /venv/bin/python -c "import shutil, karni.deploy.backup as b; shutil.copyfile(b.__file__, '/karni_backup.py')"

FROM base AS dev
WORKDIR /app
ENV PATH="/venv/bin:${PATH}"
COPY --from=deps /venv /venv
COPY . /app/
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# The staff app (frontend/), built for production. A project without
# frontend/package.json gets an empty dist and no staff app.
FROM node:24-alpine AS staff-app
WORKDIR /build
ARG KARNI_UI_TARBALL=""
ARG KARNI_APP_PATH=/app/
COPY . /build/
RUN if [ ! -f frontend/package.json ]; then mkdir -p frontend/dist; exit 0; fi \
    && cd frontend \
    && if [ -n "${KARNI_UI_TARBALL}" ]; then \
        node -e 'const fs = require("fs"); const p = JSON.parse(fs.readFileSync("package.json")); p.dependencies["@karni/ui"] = "file:../" + process.env.KARNI_UI_TARBALL; fs.writeFileSync("package.json", JSON.stringify(p, null, 4) + "\n");' \
        && rm -f package-lock.json; \
    elif grep -q '"@karni/ui": "file:' package.json; then \
        echo "frontend/package.json installs @karni/ui from a local checkout (file:), which this build cannot reach. Pack it into the project and set KARNI_UI_TARBALL (docs/deploy.md)." >&2; \
        exit 1; \
    fi \
    && if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi \
    && npm run build -- --base="${KARNI_APP_PATH}"

FROM python:3.12-slim AS prod
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIA_ROOT=/data/media \
    STATIC_ROOT=/data/static \
    PATH="/venv/bin:${PATH}"
RUN addgroup --system app && adduser --system --ingroup app app
COPY --from=deps /venv /venv
COPY . /app/
COPY --from=staff-app /build/frontend/dist /app/frontend/dist
# collectstatic at build time checks the static files collect, and gives a new
# /data volume its first copy, owned by the app user. The release step collects
# again on every start. DJANGO_ENV=dev + a dummy SECRET_KEY keep the strict
# prod validation out of a command that touches no real config.
RUN mkdir -p /data/static /data/media /data/web \
    && DJANGO_ENV=dev SECRET_KEY=build-only-dummy python manage.py collectstatic --noinput -v 0 \
    && chown -R app:app /data
USER app
EXPOSE 8000
# The deploy gate: `karni check --deploy` must pass before the command starts
# (E520). KARNI_SKIP_DEPLOY_CHECK=1 skips it in an emergency, logged loudly.
ENTRYPOINT ["python", "-m", "karni.deploy.entrypoint"]
CMD ["gunicorn", "config.asgi:application", "-k", "uvicorn_worker.UvicornWorker", "-b", "0.0.0.0:8000"]

# Backups: the PostgreSQL client tools of the database's version, Python for
# Karni's backup tool, and boto3 for an S3 bucket (KARNI_BACKUP_S3_BUCKET).
# It runs as root: a restore writes media files, then hands them to the owner
# of the media folder (the app user).
FROM postgres:${POSTGRES_VERSION}-alpine AS backup
RUN apk add --no-cache python3 py3-boto3 && mkdir -p /backups
COPY --from=deps /karni_backup.py /usr/local/lib/karni_backup.py
RUN printf '#!/bin/sh\nexec python3 /usr/local/lib/karni_backup.py "$@"\n' > /usr/local/bin/karni-backup \
    && chmod 755 /usr/local/bin/karni-backup
WORKDIR /backups
ENTRYPOINT ["karni-backup"]
CMD ["loop"]

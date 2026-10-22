# syntax=docker/dockerfile:1
# Multi-stage build for EventHub.
#
# Targets:
#   dev:  used by docker-compose. Runserver-friendly, source bind-mounted over /app.
#   prod: fresh slim image, non-root user, gunicorn with uvicorn workers.
#
# Build arg KARNI_SRC: path *inside this project* to a local karni checkout,
# installed before (and therefore instead of) the PyPI release. Until karni is
# published, vendor it and set KARNI_SRC in .env (see README.md).

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

FROM base AS deps
WORKDIR /app
RUN uv venv /venv
ARG KARNI_SRC=""
# Copy the whole context so a vendored karni checkout (KARNI_SRC) is available.
COPY . /app/
# Installing KARNI_SRC first satisfies the "karni" requirement, so the
# pyproject install below skips resolving it from PyPI.
RUN if [ -n "${KARNI_SRC}" ]; then \
        uv pip install --python /venv/bin/python "./${KARNI_SRC}"; \
    fi \
    && uv pip install --python /venv/bin/python -r pyproject.toml

FROM base AS dev
WORKDIR /app
ENV PATH="/venv/bin:${PATH}"
COPY --from=deps /venv /venv
COPY . /app/
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM python:3.12-slim AS prod
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:${PATH}"
RUN addgroup --system app && adduser --system --ingroup app app
COPY --from=deps /venv /venv
COPY . /app/
# collectstatic at build time. DJANGO_ENV=dev + a dummy SECRET_KEY keep the
# strict prod validation out of a command that touches no real config.
RUN mkdir -p /data/static /data/media \
    && DJANGO_ENV=dev SECRET_KEY=build-only-dummy python manage.py collectstatic --noinput \
    && chown -R app:app /data
USER app
EXPOSE 8000
CMD ["gunicorn", "config.asgi:application", "-k", "uvicorn_worker.UvicornWorker", "-b", "0.0.0.0:8000"]

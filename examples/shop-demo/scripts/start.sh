#!/bin/sh
# The demo's start command: the image's CMD, behind Karni's deploy gate
# (ENTRYPOINT python -m karni.deploy.entrypoint, which runs karni check --deploy
# first). Outside Docker, the same command is:
#
#   python -m karni.deploy.entrypoint sh scripts/start.sh
#
# 1. demo_boot: migrate, then seed an empty database or reset data older than
#    DEMO_RESET_HOURS. It runs alone, before any worker serves a request.
# 2. gunicorn with uvicorn workers on PORT (Render sets it, default 8000).
#    WEB_CONCURRENCY sets the workers (default 2). Each worker serves the API,
#    the admin and the React app, and checks once a minute whether a reset is due.
set -eu
cd "$(dirname "$0")/.."
python manage.py demo_boot
exec gunicorn config.asgi:application \
    --worker-class uvicorn_worker.UvicornWorker \
    --bind "${HOST:-0.0.0.0}:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --max-requests 1000 --max-requests-jitter 100

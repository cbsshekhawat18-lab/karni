"""Project package for EventHub.

Runs first for every entry point (manage.py, ASGI/WSGI, ``celery -A config``):
it loads ``.env`` for host runs (variables already set, e.g. by Docker Compose
or CI, always win; ``KARNI_DOTENV=false`` skips it), then imports the Celery
app so ``@shared_task`` binds to it whenever Django starts
(see https://docs.celeryq.dev/en/stable/django/).
"""

from karni.dotenv import load_dotenv

load_dotenv(__file__)

from config.celery import app as celery_app  # noqa: E402

__all__ = ["celery_app"]

"""Project package for {{ cookiecutter.project_name }}.

Importing the Celery app here ensures ``@shared_task`` binds to it whenever
Django starts (see https://docs.celeryq.dev/en/stable/django/).
"""

from config.celery import app as celery_app

__all__ = ["celery_app"]

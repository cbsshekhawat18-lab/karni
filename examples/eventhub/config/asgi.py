"""ASGI config for EventHub.

Exposes the ASGI callable as a module-level variable named ``application``.
This is what gunicorn runs in production (with uvicorn workers); see the
Dockerfile ``prod`` target.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()

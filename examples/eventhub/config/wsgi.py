"""WSGI config for EventHub.

Exposes the WSGI callable as a module-level variable named ``application``.
The production stack serves ASGI (config/asgi.py) by default; this module is
kept for WSGI-only hosts.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

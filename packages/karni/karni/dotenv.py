"""Load a project's ``.env`` before Karni reads its environment.

``karni.conf`` reads environment variables when it is imported — and the
Celery factory imports it while the project package initialises — so the
scaffold calls :func:`load_dotenv` at the top of ``config/__init__.py``, the
first code every entry point (manage.py, ASGI/WSGI, ``celery -A config``) runs::

    from karni.dotenv import load_dotenv

    load_dotenv(__file__)

    from config.celery import app as celery_app  # noqa: E402

Variables that are already set always win, so Docker Compose (``env_file``),
CI and an explicit ``export`` behave exactly as before; the file only fills
in what is missing for host runs (``karni serve --local``, ``karni test``).

Override / escape hatch: set ``KARNI_DOTENV=false`` to skip loading, or pass
``name=`` to read a different file. This module imports nothing from
``karni.conf``, so calling it first has no side effects on settings.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["load_dotenv"]

_FALSE = {"0", "false", "no", "off"}


def load_dotenv(settings_file: str | Path, name: str = ".env") -> Path | None:
    """Load ``<project root>/<name>`` into ``os.environ`` without overriding.

    The project root is the parent of the settings package (``config/``),
    i.e. the directory holding ``manage.py``. Returns the file loaded, or
    ``None`` when there is none or loading is disabled.
    """
    if os.environ.get("KARNI_DOTENV", "").strip().lower() in _FALSE:
        return None
    path = Path(settings_file).resolve().parent.parent / name
    if not path.is_file():
        return None
    import environ

    environ.Env.read_env(str(path), overwrite=False)
    return path

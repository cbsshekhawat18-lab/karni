"""The database probe: runs in the project's interpreter, never in the CLI's.

:mod:`karni_cli.database` passes this file's source to ``python -c`` with the
project as the working directory, where ``manage.py`` runs, so the CLI itself
never imports Django. The probe loads the project's settings as manage.py does
(``DJANGO_SETTINGS_MODULE``, default ``config.settings``), then for every
database alias loads its backend (``connections[alias]``, which imports the
driver: psycopg for PostgreSQL) and, given ``connect``, opens and closes a
connection. SQLite needs no server and is never opened, so the probe creates
no database file.

It prints one line, :data:`MARKER` followed by JSON, and exits 0:

- ``{"status": "ok"}``;
- ``{"status": "unknown"}``: the settings or the probe itself fail; the
  command's own error says why, so the guard lets it run;
- ``{"status": "driver" | "unreachable", "alias", "engine", "host", "port",
  "name", "error"}``.

Importing this module is side-effect free (Django is imported inside
:func:`probe`), so tests can call it in-process too.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

MARKER = "karni-db-probe: "
DEFAULT_SETTINGS = "config.settings"
#: Seconds the probe waits for a PostgreSQL/MySQL server to answer.
CONNECT_TIMEOUT = 5


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def probe(connect: bool) -> dict[str, Any]:
    """Load every database backend (and, with ``connect``, open a connection)."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", DEFAULT_SETTINGS)
    try:
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured
        from django.db import DatabaseError, connections

        databases = dict(settings.DATABASES)
    except Exception:  # noqa: BLE001 - settings that do not load are the command's own error
        return {"status": "unknown"}
    for alias, conf in databases.items():
        found = {
            "alias": str(alias),
            "engine": str(conf.get("ENGINE") or ""),
            "host": str(conf.get("HOST") or ""),
            "port": str(conf.get("PORT") or ""),
            "name": str(conf.get("NAME") or ""),
        }
        try:
            connection = connections[alias]
        except ImproperlyConfigured as exc:  # the backend module (or its driver) cannot load
            return {"status": "driver", **found, "error": _first_line(exc)}
        except Exception:  # noqa: BLE001 - anything else is not ours to diagnose
            return {"status": "unknown"}
        if not connect or connection.vendor == "sqlite":
            continue
        if connection.vendor in {"postgresql", "mysql"}:
            options = connection.settings_dict.setdefault("OPTIONS", {})
            options.setdefault("connect_timeout", CONNECT_TIMEOUT)
        try:
            connection.ensure_connection()
        except DatabaseError as exc:
            return {"status": "unreachable", **found, "error": _first_line(exc)}
        except Exception:  # noqa: BLE001
            return {"status": "unknown"}
        finally:
            connection.close()
    return {"status": "ok"}


def main(argv: list[str]) -> int:
    sys.stdout.write(f"{MARKER}{json.dumps(probe(connect='connect' in argv))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

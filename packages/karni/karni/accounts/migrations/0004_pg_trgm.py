"""Create the ``pg_trgm`` extension on PostgreSQL — what ``?search=`` needs.

The default search provider (``karni.api.search.postgres``) ranks a trigram
similarity leg next to full-text search, and ``similarity()`` lives in the
``pg_trgm`` extension. Nothing else in a project creates it, so this
migration does, once, wherever ``karni.accounts`` is installed (every Karni
project: it is the user model's app). It is a no-op on every other database.

``pg_trgm`` is a *trusted* extension since PostgreSQL 13, so the database
owner may create it without superuser rights. If your role may not, create
it once by hand (``CREATE EXTENSION IF NOT EXISTS pg_trgm;`` as a superuser)
and re-run ``migrate``.
"""

from __future__ import annotations

from typing import Any

from django.db import migrations

SQL = "CREATE EXTENSION IF NOT EXISTS pg_trgm"


def create_pg_trgm(apps: Any, schema_editor: Any) -> None:
    """``CREATE EXTENSION IF NOT EXISTS pg_trgm`` on PostgreSQL; nothing elsewhere."""
    if schema_editor.connection.vendor != "postgresql":
        return
    try:
        schema_editor.execute(SQL)
    except Exception as exc:  # noqa: BLE001 - name the fix, keep the database error
        raise RuntimeError(
            "karni.accounts.0004_pg_trgm: could not create the pg_trgm extension that "
            "?search= needs (the database role may lack the right). Run "
            "`CREATE EXTENSION IF NOT EXISTS pg_trgm;` as a superuser once, then migrate "
            f"again. Database said: {exc}"
        ) from exc


class Migration(migrations.Migration):
    dependencies = [("karni_accounts", "0003_matrix")]

    operations = [migrations.RunPython(create_pg_trgm, migrations.RunPython.noop)]

"""PostgreSQL extensions, created by migration, with an exact fix when the role may not.

:class:`CreateExtension` is a migration operation (and :func:`ensure_extension`
the function behind it) that creates an extension on PostgreSQL and does
nothing on any other database::

    from karni.fields import CreateExtension

    class Migration(migrations.Migration):
        operations = [CreateExtension("btree_gist")]

It checks ``pg_extension`` first, so a role without the right to create
extensions migrates fine once a DBA has created it. When the database
refuses, it raises ``karni.E966`` with the SQL to run:

* every extension: ``CREATE EXTENSION IF NOT EXISTS <name>;`` as a superuser,
  in the project's database;
* a **trusted** extension (PostgreSQL 13 and later, e.g. ``pg_trgm``,
  ``btree_gist``, ``citext``): alternatively ``GRANT CREATE ON DATABASE
  "<db>" TO "<role>";``, after which the role may create it itself. The
  database owner already holds that right.

Karni creates ``pg_trgm`` (``karni.accounts`` 0004, for ``?search=``) and
``btree_gist`` (``karni.accounts`` 0005, equality columns inside GiST
exclusion constraints) in every project. Rolling a migration back never
drops an extension: other objects may depend on it.

Override / escape hatch: create extensions yourself (``CREATE EXTENSION``
in a DBA script or ``RunSQL``) and the operation finds them present.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.migrations.operations.base import Operation

from karni.exceptions import KarniImproperlyConfigured

__all__ = ["EXTENSIONS", "CreateExtension", "Extension", "ensure_extension", "extension_fix"]


@dataclass(frozen=True)
class Extension:
    """What Karni knows about a PostgreSQL extension it may create."""

    name: str
    #: Trusted since PostgreSQL 13: a role with CREATE on the database may create it.
    trusted: bool
    #: Why Karni (or a Karni field) needs it.
    why: str


#: The extensions Karni creates or documents. Others work too (``trusted`` unknown).
EXTENSIONS: dict[str, Extension] = {
    extension.name: extension
    for extension in (
        Extension("pg_trgm", True, "trigram similarity for ?search= (karni.accounts 0004)"),
        Extension(
            "btree_gist",
            True,
            "equality on plain columns inside GiST exclusion constraints (karni.accounts 0005)",
        ),
        Extension("citext", True, "case-insensitive text type (Karni uses LOWER() indexes)"),
    )
}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def extension_fix(name: str, connection: Any) -> str:
    """The exact SQL that lets ``migrate`` create ``name`` on ``connection``'s database."""
    database = str(connection.settings_dict.get("NAME") or "<database>")
    role = str(connection.settings_dict.get("USER") or "<role>")
    create = f"CREATE EXTENSION IF NOT EXISTS {name};"
    info = EXTENSIONS.get(name)
    version = getattr(connection, "pg_version", None) or 0
    if info is not None and info.trusted and (not version or version >= 130000):
        return (
            f"Run `{create}` once in database {database} as a superuser, or let role {role} "
            f"create trusted extensions itself: `GRANT CREATE ON DATABASE {_quote(database)} TO "
            f"{_quote(role)};` (as a superuser or the database owner). Then migrate again."
        )
    return (
        f"Run `{create}` once in database {database} as a superuser ({name} is not a trusted "
        "extension, so only a superuser may create it). Then migrate again."
    )


def _installed(connection: Any, name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = %s", [name])
        return cursor.fetchone() is not None


def ensure_extension(schema_editor: Any, name: str) -> None:
    """Create extension ``name`` on PostgreSQL unless present; nothing elsewhere.

    Raises ``karni.E966`` naming the exact fix when the database refuses.
    """
    connection = schema_editor.connection
    if connection.vendor != "postgresql" or _installed(connection, name):
        return
    try:
        schema_editor.execute(f"CREATE EXTENSION IF NOT EXISTS {_quote(name)}")
    except Exception as exc:  # noqa: BLE001 - every refusal gets the fix; the cause is kept
        raise KarniImproperlyConfigured(
            f"Could not create the PostgreSQL extension {name} "
            f"({EXTENSIONS[name].why if name in EXTENSIONS else 'a migration needs it'}): the "
            f"database role may not create extensions. {extension_fix(name, connection)} "
            f"Database said: {str(exc).strip()}",
            code="E966",
        ) from exc


class CreateExtension(Operation):
    """Migration operation: :func:`ensure_extension` forwards, nothing backwards."""

    reversible = True
    reduces_to_sql = False

    def __init__(self, name: str) -> None:
        self.name = name

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        return "karni.fields.CreateExtension", [self.name], {}

    def state_forwards(self, app_label: str, state: Any) -> None:
        pass

    def database_forwards(
        self, app_label: str, schema_editor: Any, from_state: Any, to_state: Any
    ) -> None:
        ensure_extension(schema_editor, self.name)

    def database_backwards(
        self, app_label: str, schema_editor: Any, from_state: Any, to_state: Any
    ) -> None:
        pass  # never drop an extension: other objects may depend on it

    def describe(self) -> str:
        return f"Create the PostgreSQL extension {self.name} (if missing)"

    @property
    def migration_name_fragment(self) -> str:
        return f"create_extension_{self.name}"

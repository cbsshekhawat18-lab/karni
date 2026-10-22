"""Create the ``btree_gist`` extension on PostgreSQL; a no-op on every other database.

GiST indexes only know ranges, geometry and the like; an exclusion
constraint that also compares a plain column with ``=`` (the same room, the
same resource) needs ``btree_gist``'s operator classes for it. Karni's field
layer relies on it, so every project gets it here, next to ``pg_trgm``
(0004). ``btree_gist`` is a trusted extension (PostgreSQL 13+): the database
owner may create it. When the role may not, ``karni.E966`` names the exact
SQL to run (see ``karni.fields.extensions``).
"""

from __future__ import annotations

from django.db import migrations

from karni.fields.extensions import CreateExtension


class Migration(migrations.Migration):
    dependencies = [("karni_accounts", "0004_pg_trgm")]

    operations = [CreateExtension("btree_gist")]

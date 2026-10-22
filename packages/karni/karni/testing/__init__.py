"""Build-failing architecture enforcement and test tooling for Karni projects.

Architecture rules — two surfaces, one implementation:

* ``pytest --pyargs karni.testing.architecture`` — a CI test suite (it also
  carries the N+1 scaling check from :mod:`karni.testing.performance`).
* ``manage.py karni_check`` — via the ``karni.checks`` entry points this
  package registers (``architecture``, ``duplication``).

Every rule fails the build and every rule has a documented inline opt-out
with a required reason::

    # karni: allow(<rule-id>): <reason>

Rules without escape hatches cause forks, and a fork is worse than a
duplicate. See docs/enforcement.md.

Test tooling (docs/testing.md), re-exported here lazily so importing this
package stays free of test-only imports:

* ``APITestCase``, ``client_as``, ``user_with_roles``, ``assert_crud``
  (:mod:`karni.testing.api`) — clients per role, a resource's whole CRUD
  surface in one call;
* ``assert_isolated`` (:mod:`karni.testing.isolation`) — a role cannot reach
  another owner's (or tenant's) rows;
* ``assert_row_hidden`` / ``assert_admin_row_hidden`` (:mod:`karni.testing.hidden`)
  — one row outside a client's row scope behaves as "does not exist" on every
  API surface / in the admin;
* ``assert_schema_snapshot`` (:mod:`karni.testing.schema`) — the OpenAPI
  contract snapshot;
* ``query_budget`` (:mod:`karni.testing.performance`);
* :mod:`karni.testing.factories` and :mod:`karni.testing.values` —
  generated factories and the value engine ``karni seed`` shares.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from karni.testing.api import APITestCase, assert_crud, client_as, user_with_roles
    from karni.testing.hidden import assert_admin_row_hidden, assert_row_hidden
    from karni.testing.isolation import assert_isolated
    from karni.testing.performance import query_budget
    from karni.testing.schema import assert_schema_snapshot

__all__ = [
    "APITestCase",
    "assert_admin_row_hidden",
    "assert_crud",
    "assert_isolated",
    "assert_row_hidden",
    "assert_schema_snapshot",
    "client_as",
    "query_budget",
    "user_with_roles",
]

_LAZY = {
    "APITestCase": "karni.testing.api",
    "assert_admin_row_hidden": "karni.testing.hidden",
    "assert_crud": "karni.testing.api",
    "assert_isolated": "karni.testing.isolation",
    "assert_row_hidden": "karni.testing.hidden",
    "assert_schema_snapshot": "karni.testing.schema",
    "client_as": "karni.testing.api",
    "query_budget": "karni.testing.performance",
    "user_with_roles": "karni.testing.api",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *globals()])

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

Test tooling (docs/testing.md): :mod:`karni.testing.factories` (automatic
factory-boy factories), :mod:`karni.testing.performance` (query budgets and
the scaling check) and the ``karni`` pytest plugin
(:mod:`karni.testing.pytest_plugin`). ``karni.testing.query_budget`` is
re-exported lazily so importing this package stays free of test-only imports.
"""

from __future__ import annotations

from typing import Any

__all__ = ["query_budget"]


def __getattr__(name: str) -> Any:
    if name == "query_budget":
        from karni.testing.performance import query_budget

        return query_budget
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

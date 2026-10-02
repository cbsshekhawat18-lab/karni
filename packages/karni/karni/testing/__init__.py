"""Build-failing architecture enforcement for Karni projects.

Two surfaces, one implementation:

* ``pytest --pyargs karni.testing.architecture`` — a CI test suite.
* ``manage.py karni_check`` — via the ``karni.checks`` entry points this
  package registers (``architecture``, ``duplication``).

Every rule fails the build and every rule has a documented inline opt-out
with a required reason::

    # karni: allow(<rule-id>): <reason>

Rules without escape hatches cause forks, and a fork is worse than a
duplicate. See docs/enforcement.md.
"""

"""``karni upgrade``: move a project across Karni versions with the changelog's codemods.

* :mod:`.changelog` — Karni's machine-readable changelog (one TOML file per
  release in ``packages/karni/karni/changelog``) and the selection of the
  changes between two versions;
* :mod:`.codemod` — the codemod contract, and which project files it may touch;
* :mod:`.python` — data-driven libcst codemods (rename a symbol or a setting,
  replace an attribute or a method call) and detectors for manual changes;
* :mod:`.typescript` — the pinned jscodeshift runner and its data-driven
  transforms (``transforms/``);
* :mod:`.engine` — runs codemods over a scratch copy, diffs it, writes it
  back all or nothing, and builds the report;
* ``v<major>_<minor>/<name>.py`` — one module per breaking change, named by
  the release in which the old form breaks, exposing ``CODEMOD``.

Recording a breaking change:

1. append a ``[[change]]`` to ``packages/karni/karni/changelog/<release>.toml``;
2. if it is mechanical, add ``upgrades/v<X>_<Y>/<name>.py``, usually one line
   of data (``CODEMOD = RenameSymbol(old=..., new=...)``,
   ``RenameSetting(...)``, ``RenameExport(...)`` for ``@karni/ui``), plus a
   before/after test; if it is manual, optionally a detector the same way;
3. write its section in ``docs/migrations/<release>.md``; if it deprecates
   something, ``warn_deprecated(..., removed_in=..., doc_anchor=<that section>)``.

The changelog tests (packages/karni/tests/test_changelog.py,
tests/test_upgrade.py here) fail until every piece is in place.
"""

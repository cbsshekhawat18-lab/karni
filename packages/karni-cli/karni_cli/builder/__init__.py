"""Experimental. ``karni build``: apply ``karni plan`` to the project, idempotently.

The agent writes a small spec (``karni.yaml``) and Karni turns it into code
deterministically. Karni's code lives in files of its own
(:mod:`.layout`), rewritten on every build. The project's files are created
once and never overwritten, so hand-written code survives every build.

* :mod:`.layout` — which files Karni owns and which the project owns;
* :mod:`.record` — ``.karni/build.json``: a sha256 of every Karni-owned file
  and block, what Karni manages, what the project adopted, and how a hand
  edit is found;
* :mod:`.render` — the Karni-owned files and blocks, and the project's
  files, rendered from the spec;
* :mod:`.run` — the build itself: the plan's guard, the hand-edit check,
  then the steps in order (modules, files, migrations, migrate, seed, types,
  test, check);
* :mod:`.output` — the ``--json`` output and its published JSON Schema.

This package imports nothing heavy at import time: ``karni plan`` reads
:mod:`.layout` from it.
"""

"""Experimental. The app spec, ``karni.yaml``: its format, validation and export.

A spec describes a Karni project in the terms ``karni make``, ``karni add``
and the settings already use: the apps and their entities (fields in
``karni make model``'s syntax, keys, search, owner, audit, field groups,
ordering, access), the roles, the built-in features, the modules and the
pages. Anything it cannot express stays in the project's own code.

- :mod:`karni_cli.spec.schema`: the format as Pydantic models, and its JSON Schema.
- :mod:`karni_cli.spec.validate`: ``karni spec validate``, every issue with its code and line.
- :mod:`karni_cli.spec.export`: ``karni spec export``, the spec of an existing project.
- :mod:`karni_cli.spec.normal`: one canonical form, to compare two specs.

See docs/app-spec.md.
"""

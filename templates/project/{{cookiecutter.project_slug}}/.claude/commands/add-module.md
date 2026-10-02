---
description: Install an optional Karni module and wire it into settings
---
Install Karni module: $ARGUMENTS

1. Run `karni add <module>` — it adds the `karni-<module>` dependency to
   pyproject.toml and wires `karni_<module>` into the INSTALLED_APPS block
   marked `# karni:apps` in config/settings.py.
2. Rebuild/install: `docker compose build` (or `uv pip install -r
   pyproject.toml` in a host venv), then `make migrate`.
3. Run `karni context` — the module must appear under MODULES.
4. Configure only settings the module documents; do not patch its internals.

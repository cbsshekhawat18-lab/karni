"""``python -m karni_cli.recipes``: print the JSON Schema of ``recipe.toml``."""

from __future__ import annotations

import json

from karni_cli.recipes import json_schema

print(json.dumps(json_schema(), indent=2, sort_keys=False))

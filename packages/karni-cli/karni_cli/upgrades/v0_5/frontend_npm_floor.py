"""``frontend/package.json`` asks for npm 10.8, not npm 11, in ``engines``.

Changelog entry ``frontend-npm-floor`` (0.5.2). Migration note:
docs/migrations/0.5.md#the-frontend-installs-with-plain-npm-install.

Karni 0.5.0 and 0.5.1 wrote ``"npm": ">=11"``, and with ``engine-strict`` in
``frontend/.npmrc`` npm 10 stops there with EBADENGINE. npm 10 installs a
Karni frontend from its package-lock.json, so the floor is npm 10.8, the npm
Node 20.19 bundles. The codemod changes Karni's value only: a different
``npm`` range is the project's own choice and is left alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from karni_cli.upgrades.codemod import Codemod, Outcome, Site

FRONTEND_PACKAGE = "frontend/package.json"
OLD_RANGE = ">=11"
NEW_RANGE = ">=10.8"
OLD = f'"npm": "{OLD_RANGE}"'
NEW = f'"npm": "{NEW_RANGE}"'


def lower_npm_floor(text: str) -> str | None:
    """``text`` with ``engines.npm`` at 10.8, ``None`` when it does not hold Karni's ``>=11``."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    engines = data.get("engines") if isinstance(data, dict) else None
    if not isinstance(engines, dict) or engines.get("npm") != OLD_RANGE:
        return None
    return text.replace(OLD, NEW) if text.count(OLD) == 1 else None


class FrontendNpmFloor(Codemod):
    def apply(self, root: Path) -> Outcome:
        path = root / FRONTEND_PACKAGE
        if not path.is_file():
            return Outcome()
        text = path.read_text(encoding="utf-8")
        updated = lower_npm_floor(text)
        if updated is not None:
            path.write_text(updated, encoding="utf-8")
            return Outcome(files={FRONTEND_PACKAGE: 1})
        try:
            engines = json.loads(text).get("engines")
        except (json.JSONDecodeError, AttributeError):
            return Outcome()
        if isinstance(engines, dict) and engines.get("npm") == OLD_RANGE:
            note = f'set "engines": {{"npm": "{NEW_RANGE}"}} (it reads "{OLD_RANGE}")'
            return Outcome(sites=[Site(FRONTEND_PACKAGE, 0, note)])
        return Outcome()


CODEMOD = FrontendNpmFloor()

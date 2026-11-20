"""``app.recipe: shop`` in karni.yaml becomes ``app.recipes: [shop]``.

Changelog entry ``app-recipes`` (0.6.0). Migration note:
docs/migrations/0.6.md#a-project-lists-its-recipes-in-apprecipes.

A project may hold several recipes now, so karni.yaml lists them in
``app.recipes``. ``app.recipe`` is still read, as a list of one, with a
deprecation warning until 1.0. The codemod rewrites the one key in place and
keeps every other character of the file. When the result does not read back
as the same spec with the key renamed (an anchor, a layout it cannot place),
it changes nothing and reports the line instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from karni_cli.upgrades.codemod import Codemod, Outcome, Site

SPEC = "karni.yaml"
_KEY = re.compile(
    r"(?m)(?P<head>(?:^[ \t]+|[{,][ \t]*))recipe(?P<sep>:[ \t]*)(?P<name>[A-Za-z0-9_-]+)"
)


def _app(data: Any) -> dict[str, Any] | None:
    app = data.get("app") if isinstance(data, dict) else None
    return app if isinstance(app, dict) else None


def recipes_key(text: str) -> str | None:
    """``text`` with ``app.recipe`` written as ``app.recipes``; ``None`` when there is nothing to do."""
    import yaml

    try:
        before = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    app = _app(before)
    if app is None or not isinstance(app.get("recipe"), str) or "recipes" in app:
        return None
    name = app["recipe"]
    found = [m for m in _KEY.finditer(text) if m.group("name") == name]
    if len(found) != 1:
        return None
    match = found[0]
    updated = (
        text[: match.start()]
        + f"{match.group('head')}recipes{match.group('sep')}[{name}]"
        + text[match.end() :]
    )
    expected = dict(before)
    expected["app"] = {
        ("recipes" if key == "recipe" else key): ([name] if key == "recipe" else value)
        for key, value in app.items()
    }
    try:
        after = yaml.safe_load(updated)
    except yaml.YAMLError:
        return None
    return updated if after == expected else None


class RecipeList(Codemod):
    def apply(self, root: Path) -> Outcome:
        path = root / SPEC
        if not path.is_file():
            return Outcome()
        text = path.read_text(encoding="utf-8")
        updated = recipes_key(text)
        if updated is not None:
            path.write_text(updated, encoding="utf-8")
            return Outcome(files={SPEC: 1})
        for number, line in enumerate(text.splitlines(), start=1):
            if re.match(r"^[ \t]+recipe:", line):
                note = "write app.recipes: [<name>] instead of app.recipe: <name>"
                return Outcome(sites=[Site(SPEC, number, note)])
        return Outcome()


CODEMOD = RecipeList()

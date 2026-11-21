"""Game starters (experimental): ready games a new game project starts from.

``karni new "<Name>" --kind game --genre <genre>`` writes one, and ``karni
starters list`` lists them. karni-cli finds them through the
``karni.starters`` entry points: each names a folder with

- ``starter.toml``: what it is (name, title, purpose, use_when, usually_changed);
- ``game/``: the game's own files, written to ``game/<slug>/`` (its rules, scenes,
  drawing, sounds and session on ``@karni/game``, and their tests);
- ``project/``: the project's own files at their paths (``games/game.py``,
  ``games/tests/``, ``content/game.yaml``).

Every file is the project's own once written. ``__GAME_SLUG__``,
``__GAME_TITLE__`` and ``__KARNI_GAME_SPEC__`` are filled in as they are
written. The framework stays in the packages: a starter's files import it.
"""

from importlib import resources
from importlib.resources.abc import Traversable

__all__ = ["runner"]


def _folder(name: str) -> Traversable:
    return resources.files(__name__).joinpath(name)


#: The one-tap runner ("Sky Dash"): ``karni new --kind game --genre runner``.
runner = _folder("runner")

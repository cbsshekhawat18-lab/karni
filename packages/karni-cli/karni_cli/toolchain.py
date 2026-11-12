"""The Node and npm a Karni frontend needs, and what to say when a machine falls short.

The floors live here once, so ``karni doctor`` (which flags a version below
them), ``karni check`` and ``karni new`` (which name them next to ``npm
install``) never disagree. The scaffold's ``frontend/package.json`` declares
the same floors in ``engines``, and its ``.npmrc`` sets ``engine-strict``.

Why npm 10.8: it is the npm Node 20.19 bundles, and plain ``npm install``
works on it because the scaffold ships ``frontend/package-lock.json``.
Without a lock, npm before 11.6 resolves Vite 8's optional peers (vite >
@vitejs/devtools > @vitejs/devtools-vitest > vitest > vitest's own optional
peers, each pinned to one vitest version) and crashes with ``Cannot read
properties of null (reading 'edgesOut')`` whenever vitest's packages are out
of step on the registry (npm/cli#8261, fixed in npm 11.6.0). With the lock,
npm installs what it pins and never resolves those peers.
``scripts/template_lock.py`` writes the lock.
"""

from __future__ import annotations

import re

#: Vite 8's ``engines``: ``^20.19.0 || >=22.12.0``. Node 21 and 22.0 to 22.11 fall outside it.
NODE_RANGES: tuple[tuple[tuple[int, ...], tuple[int, ...] | None], ...] = (
    ((20, 19), (21,)),
    ((22, 12), None),
)
#: The oldest npm the scaffold's frontend accepts: the one Node 20.19 bundles.
NPM_FLOOR: tuple[int, ...] = (10, 8)
NPM_FLOOR_TEXT = ".".join(str(part) for part in NPM_FLOOR)
#: The ways to an npm at the floor, cheapest first.
NPM_FIX = "run `npm install -g npm@11`, or install Node 24 LTS, which bundles npm 11"

_VERSION = re.compile(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """``(20, 20, 1)`` from ``v20.20.1`` or ``10.8.2``, or ``None`` when ``text`` holds no version."""
    if text is None:
        return None
    match = _VERSION.fullmatch(text.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def node_supported(version: tuple[int, ...]) -> bool:
    return any(low <= version and (high is None or version < high) for low, high in NODE_RANGES)


def shortfall(node: str | None, npm: str | None) -> str | None:
    """Why this Node and npm cannot install a Karni frontend, with the fix, or ``None``.

    An unsupported Node is reported first, because Node 24 fixes both. A
    version that does not parse is not judged, so ``None`` means "no known
    problem", not "fine".
    """
    node_version = parse_version(node)
    if node_version is not None and not node_supported(node_version):
        return (
            f"Node {node} cannot run Vite 8, which needs Node 20.19 or later "
            "(22.12 or later on Node 22). Fix: install Node 24 LTS, which bundles npm 11"
        )
    npm_version = parse_version(npm)
    if npm_version is not None and npm_version < NPM_FLOOR:
        return (
            f"npm {npm} is below {NPM_FLOOR_TEXT}, so the frontend's `npm install` stops "
            f"with EBADENGINE (engines in frontend/package.json). Fix: {NPM_FIX}"
        )
    return None


def install_hint() -> str:
    """How to get frontend/node_modules, naming the npm floor."""
    return (
        f"Run `npm install` in frontend/ (npm {NPM_FLOOR_TEXT} or later). "
        "`karni doctor` shows the Node and npm on PATH"
    )

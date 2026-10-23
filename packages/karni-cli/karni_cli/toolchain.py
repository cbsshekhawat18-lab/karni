"""The Node and npm a Karni frontend needs, and what to say when a machine falls short.

The floors live here once, so ``karni doctor`` (which flags a version below
them), ``karni check`` and ``karni new`` (which name them next to ``npm
install``) never disagree.

Why npm 11: npm 10, which Node 20 and Node 22 bundle, crashes in ``npm
install`` of a fresh scaffold with ``Cannot read properties of null (reading
'edgesOut')``. Vite 8's optional peer chain (vite > @vitejs/devtools >
@vitejs/devtools-vitest > vitest, whose own optional peers pin exact vitest
versions) makes arborist replace a vitest node while ``#loadPeerSet`` still
walks its peers. npm 11 checks for the detached node, and npm 10.9.9, the last
10.x, does not. npm checks ``engines`` and runs the root ``preinstall`` only
after that walk, so nothing in package.json or .npmrc stops npm 10 before it
crashes. The scaffold's ``engines`` and ``engine-strict=true`` still stop an
old npm with EBADENGINE whenever it gets past the walk, as it does once a
package-lock.json exists.
"""

from __future__ import annotations

import re

#: Vite 8's ``engines``: ``^20.19.0 || >=22.12.0``. Node 21 and 22.0 to 22.11 fall outside it.
NODE_RANGES: tuple[tuple[tuple[int, ...], tuple[int, ...] | None], ...] = (
    ((20, 19), (21,)),
    ((22, 12), None),
)
#: The first npm major that installs the scaffold's frontend.
NPM_FLOOR = 11
#: The three ways to an npm at the floor, cheapest first.
NPM_FIX = (
    "use `npx npm@11 install` in frontend/ in place of `npm install`, "
    "run `npm install -g npm@11`, or install Node 24 LTS, which bundles npm 11"
)

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
    if npm_version is not None and npm_version[0] < NPM_FLOOR:
        return (
            f"npm {npm} is below {NPM_FLOOR} and crashes in the frontend's `npm install` "
            "(Cannot read properties of null (reading 'edgesOut')). "
            f"Fix: {NPM_FIX}"
        )
    return None


def install_hint() -> str:
    """How to get frontend/node_modules, naming the npm floor.

    "Run npm install" alone is wrong advice on npm 10, where that install is
    what fails, so the hint says what to run there instead.
    """
    return (
        f"Run `npm install` in frontend/ with npm {NPM_FLOOR} or later. npm 10, which Node 20 "
        f"and Node 22 bundle, crashes in that install: {NPM_FIX}. "
        "`karni doctor` shows the Node and npm on PATH"
    )

"""Write the scaffold's frontend/package-lock.json: the tree a new project installs.

Why the scaffold ships a lock: npm before 11.6 (Node 20 and 22 bundle npm 10)
crashes in `npm install` with "Cannot read properties of null (reading
'edgesOut')" when it builds a tree without a lock while vitest's packages are
out of step on the registry (npm/cli#8261, fixed in npm 11.6.0). Vite 8 leads
there through optional peers that are never installed: vite > @vitejs/devtools
> @vitejs/devtools-vitest > vitest > vitest's own optional peers, each pinned to
one vitest version. With a lock, npm installs the versions it pins and does not
resolve those peers again, so plain `npm install` works on npm 10 and 11.

@karni/ui is left out of the lock. `npm install` resolves it from package.json
and adds it, so a new project gets the newest @karni/ui release in its range,
or the local checkout `karni new` wrote, never a release older than the CLI.

Run it on Node 20, the oldest Node the frontend supports: npm picks each
package's newest version whose engines accept the running Node, so a lock
written on a newer Node can pin a package that Node 20 refuses. The lock is
written by npm 11 (through npx), which resolves the peers without crashing.

    python scripts/template_lock.py              # rewrite the lock
    python scripts/template_lock.py --any-node   # on another Node, at your own risk

packages/karni-cli/tests/test_new.py fails when the lock and the template's
package.json disagree, and names this command.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "templates" / "project" / "{{cookiecutter.project_slug}}" / "frontend"
NAME_TEMPLATE = "{{ cookiecutter.project_slug }}"
UI_PACKAGE = "@karni/ui"
UI_LINE = re.compile(r'^\s*"@karni/ui": \{\{ cookiecutter\.karni_ui \| tojson \}\},\n', re.M)
#: The project slug the lock is written for, put back as the template expression after.
PLACEHOLDER = "karni_template"
#: The npm that writes the lock: 11.6 or later resolves Vite's optional peers safely.
NPM = ("npx", "--yes", "npm@11")
NODE_MAJOR = 20
JINJA = re.compile(r"\{\{|\{%|\{#")


def render_package(text: str) -> str:
    """The template's package.json as a project gets it, without @karni/ui."""
    without_ui, count = UI_LINE.subn("", text)
    if count != 1:
        raise SystemExit(f"{FRONTEND / 'package.json'}: no single {UI_PACKAGE} line to leave out")
    rendered = without_ui.replace(NAME_TEMPLATE, PLACEHOLDER)
    if JINJA.search(rendered):
        raise SystemExit(f"{FRONTEND / 'package.json'}: a template expression is left over")
    json.loads(rendered)
    return rendered


def template_lock(lock: str) -> str:
    """npm's lock with the project name put back as the template expression."""
    if JINJA.search(lock):
        raise SystemExit("the lock holds a template delimiter, which cookiecutter would render")
    name = f'"name": "{PLACEHOLDER}-frontend"'
    if lock.count(name) != 2:
        raise SystemExit(f"expected the project name twice in the lock, found {lock.count(name)}")
    return lock.replace(name, f'"name": "{NAME_TEMPLATE}-frontend"')


def node_major() -> int | None:
    node = shutil.which("node")
    if node is None:
        return None
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)\.", out.strip())
    return int(match.group(1)) if match else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--any-node", action="store_true", help=f"run on a Node other than {NODE_MAJOR}"
    )
    args = parser.parse_args(argv)
    major = node_major()
    if major is None:
        sys.exit("node is not on PATH")
    if major != NODE_MAJOR and not args.any_node:
        sys.exit(
            f"node on PATH is {major}.x: run this on Node {NODE_MAJOR}, the oldest Node the "
            "frontend supports, so the lock pins no package Node 20 refuses (or pass --any-node)"
        )
    package = render_package((FRONTEND / "package.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="karni-template-lock-") as work:
        here = Path(work)
        (here / "package.json").write_text(package, encoding="utf-8")
        shutil.copyfile(FRONTEND / ".npmrc", here / ".npmrc")
        command = [*NPM, "install", "--package-lock-only", "--ignore-scripts", "--no-audit"]
        result = subprocess.run([*command, "--no-fund"], cwd=here, check=False)
        if result.returncode != 0:
            return result.returncode
        lock = (here / "package-lock.json").read_text(encoding="utf-8")
    target = FRONTEND / "package-lock.json"
    target.write_text(template_lock(lock), encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

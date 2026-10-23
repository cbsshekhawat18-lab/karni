"""Run docs/quickstart.md verbatim on a clean machine (the CI "quickstart" job).

Every ``sh`` block that follows a ``<!-- karni:quickstart -->`` marker is
executed in order in a fresh temporary directory. The one line that differs
from the page is the install: CI installs the checkout's packages instead of
PyPI's (``--install`` names the command), which the page documents too.
After the blocks, the app is started and its liveness URL must answer.

CI runs it on Node 24 and on Node 20 with its bundled npm 10. npm 10 crashes
in a plain ``npm install`` of the scaffold's frontend, so the page installs the
frontend with npm 11 through npx, and this script refuses a page without that
step: dropping it would let the Node 20 run pass without installing anything.

    python .github/ci/quickstart.py \
        --install "pip install -e packages/karni -e packages/karni-cli pytest pytest-django"
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "quickstart.md"
BLOCK = re.compile(r"<!-- karni:quickstart -->\s*```sh\n(.*?)```", re.S)
INSTALL_LINE = "pip install karni karni-cli pytest pytest-django"
FRONTEND_INSTALL = "cd frontend && npx --yes npm@11 install"
CI_VARIABLES = ("CI", "GITHUB_ACTIONS", "GITHUB_RUN_ID", "RUNNER_OS")


def blocks() -> list[str]:
    found = BLOCK.findall(PAGE.read_text(encoding="utf-8"))
    if len(found) < 3:
        sys.exit(f"{PAGE}: expected at least 3 quickstart blocks, found {len(found)}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", required=True, help="replaces the page's pip install line")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = parser.parse_args(argv)
    script = "\n".join(blocks())
    if INSTALL_LINE not in script:
        sys.exit(f"{PAGE}: the install line {INSTALL_LINE!r} is missing")
    if FRONTEND_INSTALL not in script:
        sys.exit(
            f"{PAGE}: the frontend install {FRONTEND_INSTALL!r} is missing. It is the step "
            "that works on Node 20's bundled npm 10, where a plain npm install crashes."
        )
    script = script.replace(INSTALL_LINE, args.install)
    work = Path(tempfile.mkdtemp(prefix="karni-quickstart-"))
    # The page is a developer's walk-through: no CI variable leaks into it
    # (with CI set, `karni test` refuses to write the project's first OpenAPI
    # snapshot, E607, which is right for a real CI and wrong for this page).
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("VIRTUAL_ENV", "DJANGO_", "KARNI_")) and k not in CI_VARIABLES
    }
    env["KARNI_UI_SRC"] = os.environ.get("KARNI_UI_SRC", str(ROOT / "packages" / "karni-ui"))
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    print(f"quickstart: running {len(blocks())} blocks in {work}", flush=True)
    steps = "set -euxo pipefail\n" + script
    project = work / "ticket_shop"
    try:
        return _run(steps, work, project, env)
    finally:
        _stop_database(project)
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


def _stop_database(project: Path) -> None:
    """Remove the PostgreSQL container the page started (`docker compose up -d --wait db`)."""
    if (project / "docker-compose.yml").exists() and shutil.which("docker"):
        subprocess.run(
            ["docker", "compose", "down", "-v"],
            cwd=project,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )


def _run(steps: str, work: Path, project: Path, env: dict[str, str]) -> int:
    result = subprocess.run(["bash", "-c", steps], cwd=work, env=env, check=False)
    if result.returncode != 0:
        print(f"quickstart: a documented command failed (exit {result.returncode})")
        return result.returncode
    python = work / ".venv" / "bin" / "python"
    server = subprocess.Popen(
        [str(python), "manage.py", "runserver", "127.0.0.1:8911", "--noreload"],
        cwd=project,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8911/health/", timeout=2) as answer:
                    if answer.status == 200:
                        print("quickstart: the app answers on /health/")
                        return 0
            except OSError:
                time.sleep(1)
        print("quickstart: the app never answered on /health/")
        return 1
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())

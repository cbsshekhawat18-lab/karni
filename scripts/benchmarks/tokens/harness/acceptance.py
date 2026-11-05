"""What the harness does after the agent stops: migrate, serve, test, build the frontend.

The harness's own run is what counts, never the agent's claim.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import paths


@dataclass
class TestOutcome:
    __test__ = False  # not a pytest class

    passed: int = 0
    total: int = 0
    error: str = ""


def free_port(candidates: range = paths.PORT_RANGE) -> int:
    """The first port in the range that nothing listens on and that can be bound."""
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as binder:
            try:
                binder.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port in {candidates.start}-{candidates.stop - 1}")


def kill_group(
    process: subprocess.Popen[bytes] | subprocess.Popen[str], grace: float = 5.0
) -> None:
    """Stop a process started with ``start_new_session=True`` and everything it started."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def migrate(project: Path, python: Path, env: dict[str, str], timeout: float = 900) -> str:
    """``manage.py migrate``. Returns "" when it worked, else what went wrong."""
    try:
        done = subprocess.run(
            [str(python), "manage.py", "migrate", "--noinput"],
            cwd=project, env=env, capture_output=True, text=True, timeout=timeout, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return "migrate timed out"
    return "" if done.returncode == 0 else f"migrate failed: {done.stderr.strip()[-600:]}"


@contextlib.contextmanager
def server(
    project: Path, python: Path, env: dict[str, str], port: int, wait: float = 90
) -> Iterator[str]:
    """Run ``manage.py runserver`` on a port and yield its base URL once it answers."""
    process = subprocess.Popen(
        [str(python), "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
        cwd=project, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"runserver exited with {process.returncode}")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.3)
        else:
            raise RuntimeError("runserver did not answer in time")
        yield f"http://127.0.0.1:{port}"
    finally:
        kill_group(process)


def parse_junit(path: Path) -> TestOutcome:
    """Passed and total from a pytest ``--junitxml`` file."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    bad = sum(
        int(s.get("failures", 0)) + int(s.get("errors", 0)) + int(s.get("skipped", 0))
        for s in suites
    )
    return TestOutcome(passed=total - bad, total=total)


def count_tests(acceptance: Path) -> int:
    """How many tests the acceptance folder has (for a run whose server never came up)."""
    done = subprocess.run(
        [_python(), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         str(acceptance)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    return sum(1 for line in done.stdout.splitlines() if "::" in line)


def _python() -> str:
    import sys

    return sys.executable


def run_tests(
    acceptance: Path, base_url: str, project: Path, python: Path, env: dict[str, str],
    report: Path, timeout: float = 900,
) -> TestOutcome:  # fmt: skip
    """Run the acceptance tests against ``base_url`` and read the result from the junit file."""
    report.unlink(missing_ok=True)
    test_env = {
        **env,
        "BENCH_BASE_URL": base_url,
        "BENCH_PROJECT": str(project),
        "BENCH_PYTHON": str(python),
    }
    try:
        subprocess.run(
            [_python(), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no",
             f"--junitxml={report}", str(acceptance)],
            cwd=acceptance, env=test_env, capture_output=True, text=True, timeout=timeout,
            check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return TestOutcome(0, count_tests(acceptance), "the acceptance tests timed out")
    if not report.is_file():
        return TestOutcome(0, count_tests(acceptance), "pytest wrote no report")
    return parse_junit(report)


def build_frontend(project: Path, env: dict[str, str], timeout: float = 900) -> tuple[bool, str]:
    """``npm run build`` in frontend/. (True, "") when it exits 0."""
    frontend = project / "frontend"
    if not (frontend / "package.json").is_file():
        return False, "there is no frontend/package.json"
    try:
        done = subprocess.run(
            ["npm", "run", "build"], cwd=frontend, env=env, capture_output=True, text=True,
            timeout=timeout, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return False, "npm run build timed out"
    return done.returncode == 0, "" if done.returncode == 0 else done.stdout[-400:]

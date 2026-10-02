from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest

from karni.agent.history_chronicle import ChronicleProvider

MARKER = "history_provider"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", f"{MARKER}: the test runs a history provider's subprocess on purpose"
    )


def spawns_chronicle(args: Any) -> bool:
    argv0 = args[0] if isinstance(args, list | tuple) and args else str(args).split(" ")[0]
    return Path(str(argv0)).name.split(".")[0] == "chronicle"


@pytest.fixture(autouse=True)
def _no_history_provider_subprocess(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Spec: with no provider set up, no provider code spawns anything.

    Fails any attempt to run Chronicle — whether or not a ``chronicle`` binary
    is on this machine's PATH — unless the test is marked ``history_provider``.
    ``pytest.fail`` raises a BaseException, so Karni's "a provider failure is
    no brief" handling cannot swallow it.
    """
    if request.node.get_closest_marker(MARKER) is None:
        real_run = subprocess.run

        def guarded(args: Any, *a: Any, **kw: Any) -> Any:
            if spawns_chronicle(args):
                pytest.fail(f"a history provider spawned {args!r} without opting in")
            return real_run(args, *a, **kw)

        def no_run(self: ChronicleProvider, repo: Path, args: list[str], command: str) -> NoReturn:
            pytest.fail(f"the Chronicle provider tried to run `chronicle {' '.join(args)}`")

        monkeypatch.setattr(subprocess, "run", guarded)
        monkeypatch.setattr(ChronicleProvider, "_run", no_run)
    yield

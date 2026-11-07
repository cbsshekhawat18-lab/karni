"""Experimental. ``karni check``'s cache: a check reruns only on the files that changed.

``manage.py karni_check`` keeps, per check and per file, what the check found
in that file, under the hash of the file's content. On the next run a file
whose hash is unchanged is not read again: its findings come from the cache.
The checks that read files one by one use it: the architecture rules that
parse the source (``raw-sql``, ``http-client``, ``access-override``,
``unpaginated-action``, ``audited-bulk-write``) and the duplication check's
fingerprints (of the project and of Karni itself). The checks that read the
whole project always run: Django's system checks (models, migrations, URL
routing), the external tables, the class-based rules and every other
``karni.checks`` hook.

The cache lives in ``.karni/local/check-cache.json`` (machine-local, ignored
by git). It is ignored whole when it was written by another Karni, Django or
Python version, or under other settings (every ``KARNI_*`` setting,
``INSTALLED_APPS`` and the ``karni.checks`` hooks are part of its
fingerprint). A check whose extra inputs changed (the audited models of
``audited-bulk-write``) drops its own entries.

``--changed`` narrows a run to some files: the file checks read only those
files and every check reports only the findings in them, while the
whole-project checks still run in full.

Override / escape hatch: ``karni check --no-cache`` (``karni_check
--no-cache``) or ``KARNI_CHECK_CACHE = False`` turn it off, and
``KARNI_CHECK_CACHE = "<path>"`` keeps it elsewhere (relative to the project
root). A ``karni.checks`` hook of a module can use :func:`active` too:
:meth:`CheckCache.per_file` caches any per-file work.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CACHE_FILE",
    "FORMAT",
    "CheckCache",
    "active",
    "fingerprint",
    "from_settings",
    "using",
]

#: The cache's place, relative to the project root (``.karni/local/`` is never committed).
CACHE_FILE: Final = Path(".karni") / "local" / "check-cache.json"
#: The file's format. A cache of another format is ignored.
FORMAT: Final = 1
_GITIGNORE: Final = "# Machine-local karni state. Never commit it.\n*\n"
_ADDRESS = re.compile(r" at 0x[0-9a-f]+")


def _stable(value: Any) -> str:
    """``repr(value)`` without object addresses, so the same settings hash the same."""
    return _ADDRESS.sub("", repr(value))


def fingerprint() -> str:
    """What every cached result depends on: the versions, the settings and the check hooks."""
    import django
    from django.conf import settings

    import karni

    parts = [
        f"format={FORMAT}",
        f"karni={getattr(karni, '__version__', '?')}",
        f"django={django.get_version()}",
        f"python={sys.version_info[:3]}",
        f"apps={_stable(list(settings.INSTALLED_APPS))}",
        "hooks="
        + ",".join(sorted(f"{e.name}={e.value}" for e in entry_points(group="karni.checks"))),
    ]
    for name in sorted(dir(settings)):
        if name.startswith("KARNI_"):
            parts.append(f"{name}={_stable(getattr(settings, name, None))}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


@dataclass
class CheckCache:
    """Experimental. Per-check, per-file results, keyed by each file's content hash.

    ``enabled=False`` computes everything and stores nothing. ``changed``
    (paths relative to ``root``) narrows a run: :meth:`wanted` says which
    files a check reads and reports on.
    """

    root: Path
    enabled: bool = True
    changed: frozenset[str] | None = None
    key: str = ""
    #: Where the cache is kept: :data:`CACHE_FILE` under ``root`` unless set.
    file: Path | None = None
    hits: int = 0
    misses: int = 0
    _entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    _extra: dict[str, str] = field(default_factory=dict)
    _hashes: dict[Path, str] = field(default_factory=dict)
    _dirty: bool = False

    @property
    def path(self) -> Path:
        return self.file if self.file is not None else self.root / CACHE_FILE

    @classmethod
    def load(
        cls,
        root: Path,
        *,
        enabled: bool = True,
        changed: Iterable[str] | None = None,
        key: str | None = None,
        file: Path | None = None,
    ) -> CheckCache:
        """The cache of ``root``: empty when off, missing, unreadable or of another fingerprint."""
        wanted = frozenset(_posix(item) for item in changed) if changed is not None else None
        cache = cls(root=root, enabled=enabled, changed=wanted, key=key or "", file=file)
        if not enabled:
            return cache
        if not cache.key:
            cache.key = fingerprint()
        try:
            data = json.loads(cache.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cache
        if not isinstance(data, dict) or data.get("fingerprint") != cache.key:
            return cache
        checks = data.get("checks")
        extra = data.get("extra")
        if isinstance(checks, dict):
            cache._entries = {name: dict(found) for name, found in checks.items()}
        if isinstance(extra, dict):
            cache._extra = {str(name): str(value) for name, value in extra.items()}
        return cache

    def relative(self, path: Path) -> str:
        """``path`` relative to the root (posix), or its absolute path outside it."""
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return resolved.as_posix()

    def wanted(self, path: Path) -> bool:
        """Whether a file check reads and reports on ``path`` (always, unless ``--changed``)."""
        return self.changed is None or self.relative(path) in self.changed

    def reports(self, location: str) -> bool:
        """Whether a finding at ``location`` (``path:line``) is reported on this run."""
        if self.changed is None:
            return True
        return location.rsplit(":", 1)[0] in self.changed

    def file_hash(self, path: Path) -> str:
        if path not in self._hashes:
            try:
                self._hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                self._hashes[path] = ""
        return self._hashes[path]

    def extra(self, check: str, value: str) -> None:
        """Declare ``check``'s inputs other than the files: a change drops its entries."""
        if self._extra.get(check) != value:
            self._entries.pop(check, None)
            self._extra[check] = value
            self._dirty = True

    def per_file(self, check: str, path: Path, compute: Callable[[], Any]) -> Any:
        """``compute()`` for ``path``, or what it returned last time for the same content.

        ``compute`` must return JSON data (lists, dicts, strings, numbers).
        """
        if not self.enabled:
            return compute()
        name, digest = self.relative(path), self.file_hash(path)
        entries = self._entries.setdefault(check, {})
        found = entries.get(name)
        if isinstance(found, dict) and found.get("hash") == digest and digest:
            self.hits += 1
            return found.get("result")
        self.misses += 1
        result = compute()
        entries[name] = {"hash": digest, "result": result}
        self._dirty = True
        return result

    def forget_missing(self) -> None:
        """Drop the entries of files that no longer exist."""
        for entries in self._entries.values():
            for name in [name for name in entries if not (self.root / name).exists()]:
                del entries[name]
                self._dirty = True

    def save(self) -> bool:
        """Write the cache atomically (creating ``.karni/local/``); ``False`` when it cannot."""
        if not self.enabled or not self._dirty:
            return True
        self.forget_missing()
        directory = self.path.parent
        data = {
            "format": FORMAT,
            "fingerprint": self.key,
            "extra": self._extra,
            "checks": self._entries,
        }
        try:
            directory.mkdir(parents=True, exist_ok=True)
            ignore = directory / ".gitignore"
            if not ignore.is_file():
                ignore.write_text(_GITIGNORE, encoding="utf-8")
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".check-cache-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, separators=(",", ":"))
                os.replace(tmp, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except (OSError, TypeError, ValueError):
            return False
        self._dirty = False
        return True

    def summary(self) -> str:
        """``check cache: 412 of 420 file results reused`` (or that it is off)."""
        scope = f", {len(self.changed)} changed file(s)" if self.changed is not None else ""
        if not self.enabled:
            return f"check cache: off{scope}"
        total = self.hits + self.misses
        return f"check cache: {self.hits} of {total} file results reused{scope}"


def _posix(item: str) -> str:
    return Path(item).as_posix().removeprefix("./")


def from_settings(
    root: Path, *, no_cache: bool = False, changed: Iterable[str] | None = None
) -> CheckCache:
    """The cache ``KARNI_CHECK_CACHE`` asks for: ``False`` is off, a path moves the file."""
    from django.conf import settings

    setting = getattr(settings, "KARNI_CHECK_CACHE", True)
    enabled = not no_cache and setting is not False and setting is not None
    file = Path(setting) if isinstance(setting, str | Path) else None
    if file is not None and not file.is_absolute():
        file = root / file
    return CheckCache.load(root, enabled=enabled, changed=changed, file=file)


_ACTIVE: list[CheckCache] = []


def active() -> CheckCache:
    """The cache of the running ``karni_check``, else one that is off (computes everything)."""
    if _ACTIVE:
        return _ACTIVE[-1]
    from karni.testing._source import project_root

    return CheckCache(root=project_root(), enabled=False)


@contextlib.contextmanager
def using(cache: CheckCache) -> Iterator[CheckCache]:
    """Make ``cache`` the one :func:`active` returns inside the block."""
    _ACTIVE.append(cache)
    try:
        yield cache
    finally:
        _ACTIVE.pop()

"""History providers: what was already asked and decided about a file.

``karni context`` shows what a project contains *now*. A **history provider**
reads a prompt-history store kept alongside the project (Gigai Chronicle's
``.chronicle/``, for example) and returns a compact brief of what was asked and
decided about one file, so an agent does not redo a decision that was already
made and reverted.

Provider, not dependency: Karni works identically with no provider installed
and no store present. Nothing here imports a history tool; with no store
detected, ``karni context --with-history`` prints the plain inventory and
``karni rules`` omits the history rule.

Stdlib-only and Django-free like the rest of :mod:`karni.agent`: the CLI runs
this in its own environment (karni's copy when importable, else the copy
bundled into karni-cli, which still carries the built-in provider).

The protocol (duck-typed — subclass nothing, import nothing from Karni):

* ``name: str`` — stable identifier, shown in the ``HISTORY:`` heading.
* ``detect(project_root: Path) -> bool`` — is a store present for this project?
* ``context(project_root: Path, path: str) -> str | None`` — brief for one file;
  ``path`` is relative to ``project_root``, POSIX separators. ``None`` (or an
  empty string) means nothing to say.
* optional ``project_context(project_root: Path) -> str | None`` — a brief when
  no file is named (``karni context --with-history`` with no path).
* optional ``full_command(project_root: Path, path: str | None) -> str | None``
  — the shell command that prints the untruncated brief; named in the line
  that ends a truncated brief.

Providers are discovered from the ``karni.history_providers`` entry-point
group. Karni registers its built-in Gigai Chronicle provider there too, and
falls back to it when karni's own metadata is not installed (the bundled
copy); an entry point with the same name replaces the built-in one.

Providers must not print and should not raise: Karni discards anything they
write to ``sys.stdout``/``sys.stderr`` and treats an exception as "no brief".
The ~300-token cap is enforced here, never left to providers.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import math
import os
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: Entry-point group a third-party package registers its provider under.
ENTRY_POINT_GROUP = "karni.history_providers"

#: Upper bound (approximate tokens) of everything ``--with-history`` appends.
#: With ``karni context``'s inventory (under ~200 tokens for a typical
#: project) the combined output stays within a few hundred tokens.
HISTORY_TOKEN_CAP = 300

#: The approximation the ``karni rules`` budget test uses: ~4 characters/token.
CHARS_PER_TOKEN = 4

#: First word of every block ``--with-history`` appends.
HEADING = "HISTORY:"

#: ``Rule.when`` value that is active when any provider detects a store.
CONDITION = "history"

#: Escape hatch: a comma-separated list that replaces condition detection for
#: ``karni rules`` (``KARNI_AGENT_CONDITIONS=`` = never emit conditional rules).
#: The CLI also uses it to hand its own detection to the project interpreter.
CONDITIONS_ENV = "KARNI_AGENT_CONDITIONS"

#: Built-in providers as ``(name, module in this package, attribute)``. Loaded
#: relative to this package, so the copy bundled into karni-cli finds them
#: even when karni itself (and its entry-point metadata) is not installed.
BUILTIN: tuple[tuple[str, str, str], ...] = (
    ("gigai-chronicle", "history_chronicle", "ChronicleProvider"),
)


@runtime_checkable
class HistoryProvider(Protocol):
    """The required part of the protocol (see the module docstring)."""

    name: str

    def detect(self, project_root: Path) -> bool: ...

    def context(self, project_root: Path, path: str) -> str | None: ...


@dataclass(frozen=True)
class Discovered:
    """Every usable provider, plus why any registered one was skipped."""

    providers: tuple[HistoryProvider, ...]
    errors: tuple[str, ...] = ()

    @property
    def names(self) -> list[str]:
        return [provider.name for provider in self.providers]

    def third_party(self) -> tuple[HistoryProvider, ...]:
        builtin = {name for name, _module, _attr in BUILTIN}
        return tuple(p for p in self.providers if p.name not in builtin)


# --- discovery ---------------------------------------------------------------------


def _looks_like_provider(obj: object) -> bool:
    return (
        isinstance(getattr(obj, "name", None), str)
        and bool(getattr(obj, "name", ""))
        and callable(getattr(obj, "detect", None))
        and callable(getattr(obj, "context", None))
    )


def _instantiate(obj: Any) -> HistoryProvider | None:
    """An entry point may name a class, a factory, or a ready instance."""
    if isinstance(obj, type) or (callable(obj) and not _looks_like_provider(obj)):
        obj = obj()
    return obj if _looks_like_provider(obj) else None


def _entry_points() -> list[Any]:
    try:
        from importlib.metadata import entry_points

        return list(entry_points(group=ENTRY_POINT_GROUP))
    except Exception:  # noqa: BLE001 - broken metadata must never break the CLI
        return []


def _builtin(module: str, attribute: str) -> Any:
    package = __name__.rsplit(".", 1)[0]
    return getattr(importlib.import_module(f"{package}.{module}"), attribute)


def _karnis_own(entry: Any) -> bool:
    """Karni's registration of its built-ins (it loses to anyone else's)."""
    return str(entry.value).startswith("karni.agent.")


def discover() -> Discovered:
    """Entry-point providers, then any built-in whose name is not taken, by name.

    A third-party entry point wins over Karni's own registration of the same
    name, so registering ``gigai-chronicle`` replaces the built-in provider.
    """
    found: dict[str, HistoryProvider] = {}
    seen_values: dict[str, str] = {}
    errors: list[str] = []
    for entry in sorted(_entry_points(), key=_karnis_own):  # stable: third parties first
        label = f"{entry.name} ({entry.value})"
        if entry.name in seen_values:
            if seen_values[entry.name] != entry.value and not _karnis_own(entry):
                errors.append(f"{label}: name already registered by {seen_values[entry.name]}")
            continue
        seen_values[entry.name] = entry.value
        try:
            provider = _instantiate(entry.load())
        except Exception as exc:  # noqa: BLE001 - a broken plugin is reported, not raised
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        if provider is None:
            errors.append(f"{label}: not a history provider (needs name, detect, context)")
            continue
        found.setdefault(provider.name, provider)
    for name, module, attribute in BUILTIN:
        if name in found:
            continue
        try:
            provider = _instantiate(_builtin(module, attribute))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name} (built-in): {type(exc).__name__}: {exc}")
            continue
        if provider is not None:
            found[provider.name] = provider
    return Discovered(tuple(found[name] for name in sorted(found)), tuple(errors))


# --- calling providers safely --------------------------------------------------------


@contextlib.contextmanager
def _silenced() -> Iterator[None]:
    """Whatever a provider prints must never reach Karni's machine-readable output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


def _safe(call: Callable[[], Any]) -> Any:
    try:
        with _silenced():
            return call()
    except Exception:  # noqa: BLE001 - a provider failure is "no brief", never an error
        return None


def _providers(providers: Iterable[HistoryProvider] | None) -> Iterable[HistoryProvider]:
    return discover().providers if providers is None else providers


def detected(
    project_root: str | Path, providers: Iterable[HistoryProvider] | None = None
) -> list[HistoryProvider]:
    """The providers that find a store for ``project_root`` (cheap: no briefs built)."""
    root = Path(project_root)

    def finds_store(provider: HistoryProvider) -> bool:
        return bool(_safe(lambda: provider.detect(root)))

    return [provider for provider in _providers(providers) if finds_store(provider)]


def store_detected(
    project_root: str | Path, providers: Iterable[HistoryProvider] | None = None
) -> bool:
    return bool(detected(project_root, providers))


def active_conditions(
    root: str | Path | None, providers: Iterable[HistoryProvider] | None = None
) -> frozenset[str]:
    """Conditions a :class:`~karni.agent.rules.Rule` ``when`` may name, for ``root``.

    ``KARNI_AGENT_CONDITIONS`` (comma-separated, possibly empty) replaces
    detection when set. Without a project there is no store, so none apply.
    """
    forced = os.environ.get(CONDITIONS_ENV)
    if forced is not None:
        return frozenset(c.strip() for c in forced.split(",") if c.strip())
    if root is None:
        return frozenset()
    return frozenset({CONDITION}) if store_detected(root, providers) else frozenset()


# --- composition and the cap ---------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Approximate tokens: ``ceil(len / CHARS_PER_TOKEN)`` (the rules-budget measure)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def cap_lines(lines: Sequence[str], max_tokens: int, last_line: str) -> list[str]:
    """``lines`` unchanged when they fit in ``max_tokens``; otherwise the longest
    prefix of whole lines that fits together with ``last_line``, then ``last_line``.

    The first line (a heading) is always kept. When not even the next line fits
    whole, it is cut at a character boundary with ``…`` so the brief is never
    reduced to its heading alone.
    """
    if estimate_tokens("\n".join(lines)) <= max_tokens:
        return list(lines)
    kept: list[str] = list(lines[:1])
    for line in lines[1:]:
        if estimate_tokens("\n".join([*kept, line, last_line])) > max_tokens:
            break
        kept.append(line)
    if len(kept) == 1 and len(lines) > 1:
        room = max_tokens * CHARS_PER_TOKEN - len("\n".join([*kept, last_line])) - 2
        if room > 0:
            kept.append(lines[1][:room] + "…")
    return [*kept, last_line]


def _brief(provider: HistoryProvider, root: Path, path: str | None) -> list[str]:
    if path is None:
        project_context = getattr(provider, "project_context", None)
        if not callable(project_context):
            return []
        brief = _safe(lambda: project_context(root))
    else:
        brief = _safe(lambda: provider.context(root, path))
    if not isinstance(brief, str):
        return []
    return [line.rstrip() for line in brief.splitlines() if line.strip()]


def _truncation_line(
    provider: HistoryProvider, root: Path, path: str | None, max_tokens: int
) -> str:
    full_command = getattr(provider, "full_command", None)
    command = _safe(lambda: full_command(root, path)) if callable(full_command) else None
    if isinstance(command, str) and command.strip():
        return f"… truncated at ~{max_tokens} tokens; full brief: {command.strip()}"
    return f"… truncated at ~{max_tokens} tokens; {provider.name} holds the full brief"


def compose(
    project_root: str | Path,
    path: str | None = None,
    *,
    providers: Iterable[HistoryProvider] | None = None,
    max_tokens: int = HISTORY_TOKEN_CAP,
) -> str | None:
    """The block ``karni context --with-history [path]`` appends, or ``None``.

    One ``HISTORY: <path or "project"> (<provider>)`` heading per provider that
    detects a store and has something to say, followed by its brief (blank
    lines dropped). All blocks together stay within ``max_tokens`` (estimated
    with :func:`estimate_tokens`), truncated at line boundaries with a final
    line saying how to get the full brief. ``None`` when no store is detected or
    no provider had anything — the caller then prints nothing at all.
    """
    root = Path(project_root)
    target = path if path is not None else "project"
    out: list[str] = []
    for provider in detected(root, providers):
        brief = _brief(provider, root, path)
        if not brief:
            continue
        lines = [f"{HEADING} {target} ({provider.name})", *brief]
        last = _truncation_line(provider, root, path, max_tokens)
        # ceil((a + 1 + b) / 4) <= ceil((a + 1) / 4) + ceil(b / 4): the sum stays capped.
        remaining = max_tokens - (estimate_tokens("\n".join(out) + "\n") if out else 0)
        if out and estimate_tokens("\n".join([lines[0], last])) >= remaining:
            break  # no room left for another provider's brief
        capped = cap_lines(lines, remaining, last)
        out += capped
        if capped != lines:
            break  # truncated: the budget is spent
    return "\n".join(out) if out else None

"""Blocks no template shows any more: which they are, and what the scan cannot see.

A block is stored the first time a page renders its ``{% editable %}`` or
``{% editable_image %}``. When the tag leaves the template, the row stays, and
*Page content* would list it like a live block: a client could edit text no
page shows. This module tells the rows apart by reading the project's
templates, never by rendering a page, so an admin request costs one pass over
the template files (repeated only when a file changed). Each block is:

* **in a template** (``True``): its key is written in quotes in a tag of a
  template: ``{% editable "home.title" %}``, ``{% editable_image "home.hero" %}``,
  a tag of the project's own around them, ``{% include "..." with key="home.cta" %}``
  or ``{% with %}``. Or it lies under the ``editable="..."`` of a
  ``{% karni_form %}`` (the form's labels, placeholders, button and sent message),
  or ``KARNI_SITE_CODE_BLOCKS`` names it;
* **not seen** (``None``): no template names it, but a key the scan cannot read
  could be it. An ``{% editable %}``, ``{% editable_image %}`` or
  ``{% karni_form editable=... %}`` whose key is a variable or built with a filter
  is read when the page renders, so the keys under its quoted start
  (``"team."|add:slug`` covers ``team.*``) are unsure, and every key is when it
  has none. When no template has a block tag at all, every key is unsure too;
* **an orphan** (``False``): neither. No page shows it.

When unsure, a block is *not seen*, never an orphan: a wrong "orphan" invites
deleting text a page shows.

What the scan cannot see:

* keys code of your own passes to :func:`karni_site.blocks.text` or
  :func:`~karni_site.blocks.image` (a view, a middleware, a tag of your own
  given a variable). Name them in ``KARNI_SITE_CODE_BLOCKS``, shell wildcards
  allowed (``"promo.*"``);
* templates no Django template engine loads from a folder (a loader of your
  own, another engine). A commented-out tag (``{# #}``, ``{% comment %}``) is
  not a use: the scan reads templates the way Django does.

The folders read are each Django engine's ``DIRS`` and, when the engine reads
the apps' templates, every installed app's ``templates/`` except Django's own.

Override / escape hatch: ``KARNI_SITE_CODE_BLOCKS``. :func:`scan` and
:func:`classify` are the functions the admin, ``manage.py karni_site_orphans``
and ``karni check`` (``SITE025``) call, for code of your own.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from karni_site import conf

__all__ = [
    "TemplateKeys",
    "Unread",
    "classify",
    "forget",
    "scan",
    "template_folders",
    "warning",
]

WARNING_CODE = "SITE025"
#: The tags whose first argument is a block key.
BLOCK_TAGS = frozenset({"editable", "editable_image"})
#: A template larger than this is not a template: it is not read.
_MAX_BYTES = 2_000_000
_QUOTED = re.compile(r"""(["'])((?:(?!\1).)*)\1""")
_LEADING = re.compile(r"""^(["'])((?:(?!\1).)*)\1""")


def _key_pattern() -> re.Pattern[str]:
    from karni_site.models import KEY_PATTERN

    return re.compile(KEY_PATTERN)


@dataclass(frozen=True)
class Unread:
    """A block key the scan cannot read: its quoted start (``""`` for none) and where it is."""

    prefix: str
    where: str


@dataclass(frozen=True)
class TemplateKeys:
    """What the templates say about block keys."""

    #: Every block key written in quotes in a tag.
    keys: frozenset[str]
    #: ``"<key>."`` of every ``{% karni_form ... editable="<key>" %}``: the keys under it are used.
    prefixes: frozenset[str]
    #: The block tags whose key is read only when the page renders.
    unread: tuple[Unread, ...]
    #: How many block tags there are: ``{% editable %}``, ``{% editable_image %}``, editable forms.
    tags: int

    def status(self, key: str, code: Iterable[str] = ()) -> bool | None:
        """``True`` in a template, ``False`` an orphan, ``None`` not seen (see the module)."""
        if key in self.keys or key.startswith(tuple(self.prefixes)):
            return True
        if any(fnmatchcase(key, str(pattern)) for pattern in code):
            return True
        if not self.tags or any(key.startswith(found.prefix) for found in self.unread):
            return None
        return False


def template_folders() -> list[Path]:
    """The folders the Django template engines load from, Django's own apps' left out."""
    from django.apps import apps
    from django.conf import settings

    from karni_site.checks import DJANGO_BACKEND

    found: list[Path] = []
    for engine in getattr(settings, "TEMPLATES", []):
        if engine.get("BACKEND") != DJANGO_BACKEND:
            continue
        found.extend(Path(directory) for directory in engine.get("DIRS", []))
        loaders = repr(engine.get("OPTIONS", {}).get("loaders") or "")
        if engine.get("APP_DIRS") or "app_directories" in loaders:
            found.extend(
                Path(config.path) / "templates"
                for config in apps.get_app_configs()
                if config.name.split(".")[0] != "django"
            )
    unique: list[Path] = []
    for folder in found:
        if folder.is_dir() and folder not in unique:
            unique.append(folder)
    return unique


def _files(folders: list[Path]) -> list[tuple[Path, int, int]]:
    """``(path, mtime, size)`` of every template file: what tells a changed folder."""
    found: list[tuple[Path, int, int]] = []
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.is_file() and stat.st_size <= _MAX_BYTES:
                found.append((path, stat.st_mtime_ns, stat.st_size))
    return found


def _literal(bit: str) -> str | None:
    if len(bit) >= 2 and bit[0] in "\"'" and bit[-1] == bit[0] and bit[0] not in bit[1:-1]:
        return bit[1:-1]
    return None


def _start(bit: str) -> str:
    """The quoted text an expression starts with (``"team."|add:x`` gives ``team.``), or ``""``."""
    match = _LEADING.match(bit)
    return match.group(2) if match else ""


@dataclass
class _Reading:
    keys: set[str]
    prefixes: set[str]
    unread: list[Unread]
    tags: int = 0


def _read(path: Path, text: str, reading: _Reading, key: re.Pattern[str]) -> None:
    from django.template.base import Lexer, TokenType
    from django.utils.text import smart_split

    in_comment = False
    for token in Lexer(text).tokenize():
        if token.token_type not in (TokenType.BLOCK, TokenType.VAR):
            continue
        try:
            bits = token.split_contents()
        except (StopIteration, ValueError):  # an unfinished _("..."): read it plainly
            bits = list(smart_split(token.contents))
        if not bits:
            continue
        if token.token_type == TokenType.BLOCK:
            if in_comment:
                in_comment = bits[0] != "endcomment"
                continue
            if bits[0] == "comment":
                in_comment = True
                continue
        for bit in bits:
            reading.keys.update(
                found.group(2) for found in _QUOTED.finditer(bit) if key.match(found.group(2))
            )
        if token.token_type != TokenType.BLOCK:
            continue
        where = f"{path}:{token.lineno}"
        if bits[0] in BLOCK_TAGS and len(bits) >= 2:
            reading.tags += 1
            if _literal(bits[1]) is None:
                reading.unread.append(Unread(_start(bits[1]), where))
        elif bits[0] == "karni_form":
            for bit in bits[2:]:
                if not bit.startswith("editable="):
                    continue
                value = bit.removeprefix("editable=")
                reading.tags += 1
                literal = _literal(value)
                if literal is None:
                    reading.unread.append(Unread(_start(value), where))
                elif literal:
                    reading.prefixes.add(f"{literal}.")


def _scan(files: list[tuple[Path, int, int]]) -> TemplateKeys:
    reading = _Reading(set(), set(), [])
    pattern = _key_pattern()
    for path, _mtime, _size in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "{%" in text or "{{" in text:
            _read(path, text, reading, pattern)
    return TemplateKeys(
        frozenset(reading.keys), frozenset(reading.prefixes), tuple(reading.unread), reading.tags
    )


_lock = threading.Lock()
_memo: dict[str, Any] = {}


def scan() -> TemplateKeys:
    """What the templates say, read again only when a template file changed."""
    files = _files(template_folders())
    signature = tuple((str(path), mtime, size) for path, mtime, size in files)
    with _lock:
        if _memo.get("signature") == signature:
            found: TemplateKeys = _memo["found"]
            return found
    found = _scan(files)
    with _lock:
        _memo.update(signature=signature, found=found)
    return found


def forget() -> None:
    """Drop the remembered scan: the next :func:`scan` reads every template again."""
    with _lock:
        _memo.clear()


def code_keys() -> list[str]:
    """``KARNI_SITE_CODE_BLOCKS``: the keys code of the project's own stores."""
    return [str(pattern) for pattern in conf.get("KARNI_SITE_CODE_BLOCKS") or ()]


def classify(keys: Iterable[str], found: TemplateKeys | None = None) -> dict[str, bool | None]:
    """``{key: status}``: ``True`` in a template, ``False`` an orphan, ``None`` not seen."""
    found = found if found is not None else scan()
    code = code_keys()
    return {key: found.status(key, code) for key in keys}


def warning() -> str | None:
    """``SITE025`` when blocks are orphans, for ``karni check``. ``None`` when there are none,
    or when the database cannot be read (before ``migrate``, without a database)."""
    from karni_site.models import Block

    try:
        keys = list(Block.objects.order_by("key").values_list("key", flat=True))
    except Exception:  # noqa: BLE001 - no database, or not migrated: a warning never fails a run
        return None
    orphans = [key for key, status in classify(keys).items() if status is False]
    if not orphans:
        return None
    shown = ", ".join(orphans[:10]) + (" ..." if len(orphans) > 10 else "")
    return (
        f"{WARNING_CODE}: {len(orphans)} block(s) are in no template, so no page shows them, and "
        f"the admin's Page content still offers them for editing: {shown}. List them with "
        "`python manage.py karni_site_orphans`, and remove them with --delete. A key code of "
        "your own stores goes in KARNI_SITE_CODE_BLOCKS."
    )

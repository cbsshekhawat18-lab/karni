"""The system check warnings of a management command, in one short line.

Django prints every warning in full each time a command starts, so ``karni migrate``,
``karni seed`` or ``karni serve`` repeat the same paragraphs on every run. With
``KARNI_SYSTEM_CHECK_OUTPUT=short`` in the environment (the ``karni`` command sets it
for the project commands it runs, ``karni check`` excepted), ``BaseCommand.check`` prints

    System check identified 5 warnings (karni.W101, karni.W965, karni.W967 x3).
    `karni check` lists them in full.

in place of the paragraphs. Errors are never shortened: a failing check raises
``SystemCheckError`` with its full text, and so does any output this module cannot
read. Without the variable nothing changes.

Override / escape hatch: unset the variable (or set it to ``full``), or run
``python manage.py check`` to read every warning.
"""

from __future__ import annotations

import io
import os
import re
from collections import Counter
from typing import Any, Final

from django.core.management.base import BaseCommand, OutputWrapper

__all__ = ["ENV", "connect", "shorten"]

#: The environment variable that turns the short form on.
ENV: Final = "KARNI_SYSTEM_CHECK_OUTPUT"

_ISSUE: Final = re.compile(r"^\S.*?: \(([\w.]+)\)", re.MULTILINE)
_MARK: Final = "_karni_short_check"


def shorten(text: str) -> str | None:
    """The one-line summary of Django's check output ``text``, or ``None`` if it is not one."""
    if "System check identified some issues" not in text:
        return None
    ids = _ISSUE.findall(text)
    if not ids:
        return None
    counts = Counter(ids)
    listed = ", ".join(code if n == 1 else f"{code} x{n}" for code, n in counts.items())
    noun = "warning" if len(ids) == 1 else "warnings"
    return (
        f"System check identified {len(ids)} {noun} ({listed}). `karni check` lists them in full."
    )


def connect() -> None:
    """Wrap ``BaseCommand.check`` once, when :data:`ENV` is ``short``."""
    if os.environ.get(ENV) != "short" or getattr(BaseCommand.check, _MARK, False):
        return
    original = BaseCommand.check

    def check(self: BaseCommand, *args: Any, **kwargs: Any) -> Any:
        real = self.stderr
        held = io.StringIO()
        self.stderr = OutputWrapper(held)
        try:
            result = original(self, *args, **kwargs)
        finally:
            self.stderr = real
        text = held.getvalue()
        if text:
            short = shorten(text)
            real.write(short if short is not None else text.rstrip("\n"), lambda line: line)
        return result

    setattr(check, _MARK, True)
    BaseCommand.check = check  # type: ignore[method-assign]

"""Plural names for the admin: "Categories", not "Categorys".

Django's default ``verbose_name_plural`` is the singular plus an ``s``, which
is wrong for ``Category``, ``Entry``, ``Country`` and ``Log entry``. Karni
shows a correct English plural wherever the admin shows one, for every
registered model whose ``Meta`` does not declare ``verbose_name_plural``
(:func:`apply_plurals`, run by autodiscovery). A model that declares its own
plural always wins, and nothing is written to ``Meta`` as the migration
autodetector sees it, so a project gets no migration from this.

Rules for the last word: a consonant plus ``y`` becomes ``ies``, ``s``, ``x``,
``z``, ``ch`` and ``sh`` take ``es``, a name already plural (``settings``)
stays, and :data:`IRREGULAR` and :data:`UNCOUNTABLE` hold the common
exceptions. Another language keeps Django's rule (an ``s``), as the rules are
English.

Override / escape hatch: ``class Meta: verbose_name_plural = "..."`` on the
model. Add to :data:`IRREGULAR` from a project's ``AppConfig.ready`` for a word
the list lacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils.functional import lazy
from django.utils.translation import get_language

if TYPE_CHECKING:
    from django.contrib.admin import AdminSite

__all__ = ["IRREGULAR", "UNCOUNTABLE", "apply_plurals", "plural_of"]

IRREGULAR: dict[str, str] = {
    "person": "people",
    "man": "men",
    "woman": "women",
    "child": "children",
    "foot": "feet",
    "tooth": "teeth",
    "mouse": "mice",
    "goose": "geese",
    "ox": "oxen",
    "datum": "data",
    "criterion": "criteria",
    "phenomenon": "phenomena",
    "analysis": "analyses",
    "basis": "bases",
    "crisis": "crises",
    "diagnosis": "diagnoses",
    "thesis": "theses",
    "axis": "axes",
    "leaf": "leaves",
    "life": "lives",
    "wife": "wives",
    "knife": "knives",
    "shelf": "shelves",
    "half": "halves",
    "wolf": "wolves",
    "thief": "thieves",
    "loaf": "loaves",
    "hero": "heroes",
    "potato": "potatoes",
    "tomato": "tomatoes",
    "echo": "echoes",
    "veto": "vetoes",
}
"""Singular to plural for the words the rules get wrong."""

UNCOUNTABLE = frozenset(
    {
        "series",
        "species",
        "sheep",
        "fish",
        "news",
        "equipment",
        "information",
        "data",
        "metadata",
        "staff",
        "feedback",
        "software",
        "hardware",
        "advice",
        "research",
        "traffic",
    }
)
"""Words whose plural is the word itself."""

_VOWELS = frozenset("aeiou")
_ES_ENDINGS = ("s", "x", "z", "ch", "sh")
_STAYS_SINGULAR = ("ss", "us", "is", "as")


def _plural_word(word: str) -> str:
    lower = word.lower()
    if lower in UNCOUNTABLE:
        return word
    if lower in IRREGULAR:
        found = IRREGULAR[lower]
        return found.capitalize() if word[:1].isupper() else found
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in _VOWELS:
        return word[:-1] + "ies"
    if lower.endswith("s") and not lower.endswith(_STAYS_SINGULAR):
        return word  # already plural: settings, analytics
    if lower.endswith(_ES_ENDINGS):
        return word + "es"
    return word + "s"


def plural_of(name: str) -> str:
    """The English plural of a (possibly several-word) name: ``log entry`` is ``log entries``.

    >>> plural_of("category")
    'categories'
    """
    head, space, last = name.rpartition(" ")
    return head + space + _plural_word(last) if last else name


def _shown(opts: Any) -> str:
    singular = str(opts.verbose_name)
    language = get_language() or "en"
    if language.lower().startswith("en"):
        return plural_of(singular)
    return f"{singular}s"


_lazy_plural = lazy(_shown, str)


def apply_plurals(site: AdminSite) -> None:
    """Give each registered model without its own plural the correct one (module docstring).

    Idempotent. The value is lazy, so it follows the active language and a
    ``verbose_name`` that is itself translated.
    """
    for model in site._registry:
        opts = model._meta
        if "verbose_name_plural" in opts.original_attrs or getattr(opts, "_karni_plural", False):
            continue
        opts.verbose_name_plural = _lazy_plural(opts)
        opts._karni_plural = True

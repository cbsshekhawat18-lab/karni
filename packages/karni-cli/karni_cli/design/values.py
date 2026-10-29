"""Values in a designer's markup: text, highlighted words, numbers, prices, dates, names.

What :mod:`karni_cli.design.analyze` infers and :mod:`karni_cli.design.extract`
writes, read the same way by both:

* :func:`text_of` is an element's text with entities decoded and whitespace
  collapsed. ``<br>`` is a line break. Words the design highlights inside a
  heading or a paragraph (``<em>``, ``<span class="accent">``, ``<mark>``)
  are kept between two markers, ``==marked words==`` (:data:`HIGHLIGHT_MARKER`),
  the convention ``KARNI_SITE_HIGHLIGHT`` sets for the whole site: a client
  types it in an editable block, and ``{{ value|highlight }}`` (``karni_site``)
  turns it back into the design's markup. A backslash before a marker keeps it
  as text.
* :func:`number`, :func:`price` and :func:`date` read a value only when the
  whole text is one (``"12 weeks"`` with the unit kept apart, ``"€4.50"``,
  ``"14 March 2026"``). A number's thousands separators are read as such
  (``"4,000"`` is 4000, ``"1 234"`` is 1234), and a page whose ``<html
  lang>`` writes decimals with a comma is read that way (``"1.234,5"``,
  ``"4,5"``): :func:`decimal_mark`.
* :func:`slugify`, :func:`snake` and :func:`pascal` make keys and names from
  the markup's own words.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date as Date
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any, Final

from karni_cli.design.parse import Node, collapse

__all__ = [
    "HIGHLIGHT_MARKER",
    "INLINE",
    "date",
    "decimal_mark",
    "highlight_spec",
    "is_utility_class",
    "mark_pattern",
    "number",
    "page_language",
    "pascal",
    "plural",
    "price",
    "semantic_classes",
    "singular",
    "slugify",
    "snake",
    "text_of",
    "unmark",
    "words",
]

#: What goes around highlighted words: KARNI_SITE_HIGHLIGHT's default marker (karni_site), so
#: a field extracted from a design and an editable block mark words the same way. A content
#: map's top-level "marker" overrides it for ``karni design extract``.
HIGHLIGHT_MARKER: Final = "=="

#: Elements that sit inside a line of text (phrasing content).
INLINE: Final = frozenset(
    {
        "a",
        "abbr",
        "b",
        "bdi",
        "bdo",
        "br",
        "cite",
        "code",
        "data",
        "del",
        "dfn",
        "em",
        "i",
        "ins",
        "kbd",
        "mark",
        "q",
        "s",
        "samp",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "time",
        "u",
        "var",
        "wbr",
    }
)
#: Inline elements whose words a design sets apart from the rest of a line.
EMPHASIS: Final = frozenset({"em", "i", "strong", "b", "mark", "span", "u"})
#: Words for layout and widgets, not for content: never a model's or a field's name.
UI_WORDS: Final = frozenset(
    {
        "area",
        "badge",
        "block",
        "body",
        "box",
        "card",
        "carousel",
        "cell",
        "chip",
        "col",
        "column",
        "component",
        "container",
        "content",
        "element",
        "entry",
        "group",
        "grid",
        "holder",
        "inner",
        "item",
        "js",
        "layout",
        "link",
        "list",
        "media",
        "module",
        "outer",
        "panel",
        "pill",
        "row",
        "section",
        "slider",
        "stack",
        "tab",
        "tile",
        "track",
        "unit",
        "viewport",
        "widget",
        "wrap",
        "wrapper",
    }
)
#: Utility classes of the common CSS frameworks (Bootstrap, Tailwind): never a name.
_UTILITY = re.compile(
    r"""^(?:
        [mp][trblxyse]?-.* | (?:col|row|g|gx|gy|gap|order|offset)(?:-.*)?
      | (?:text|bg|fw|fs|lh|d|flex|align|justify|border|rounded|shadow|position|top|bottom
         |start|end|w|h|mw|mh|vw|vh|overflow|float|opacity|z|font|leading|tracking|grid
         |place|items|self|content|space|divide|ring|inset|translate|rotate|scale|transition
         |duration|ease|delay|animate|cursor|select|object|aspect|visually|sr|clearfix|ratio
         |stretched|initialism|hidden|visible|invisible|block|inline|sticky|fixed|absolute
         |relative|static|is|has|js|reveal|fade|show|active|current|collapse|collapsed
         |selected|open|first|last
        )(?:-.*)?
    )$""",
    re.VERBOSE,
)
_DIGIT = re.compile(r"\d")
_SLUG_DROP = re.compile(r"[^\w\s-]")
_SLUG_JOIN = re.compile(r"[-\s_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_MONTHS: Final = {
    name: index
    for index, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
_DAY_MONTH_YEAR = re.compile(
    r"^(?:[A-Za-z]{3,9}\.?,?\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})$"
)
_MONTH_DAY_YEAR = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_CURRENCIES: Final = {"€": "EUR", "$": "USD", "£": "GBP", "¥": "JPY", "₹": "INR", "₩": "KRW"}
_CODES: Final = frozenset({"EUR", "USD", "GBP", "JPY", "INR", "CHF", "AUD", "CAD", "SEK", "NOK"})
_AMOUNT = r"(\d{1,3}(?:[ ,.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_PRICE = re.compile(
    rf"^(?P<before>[^\d]*?)(?P<cur1>[€$£¥₹₩]|\b(?:{'|'.join(sorted(_CODES))})\b)?\s*{_AMOUNT}"
    rf"\s*(?P<cur2>[€$£¥₹₩]|\b(?:{'|'.join(sorted(_CODES))})\b)?(?P<after>[^\d]*)$"
)
#: Separators between groups of three digits: a comma, a dot, an apostrophe, a space.
_GROUP_SEPARATORS: Final = ",.'’\u00a0\u202f "
_NUMBER = re.compile(
    r"^(?P<before>[^\d+\-]{0,12}?)"
    r"(?P<value>[+-]?(?:\d{1,3}(?:[,.'’\u00a0\u202f ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?))"
    r"(?P<after>\D{0,16})$"
)
#: Languages that write a decimal comma (``4,5``), by their primary subtag (CLDR).
_COMMA_LANGUAGES: Final = frozenset(
    {
        "af", "az", "be", "bg", "bs", "ca", "cs", "da", "de", "el", "es", "et", "eu", "fi",
        "fo", "fr", "gl", "hr", "hu", "hy", "id", "is", "it", "ka", "kk", "ky", "lt", "lv",
        "mk", "mn", "nb", "nl", "nn", "no", "pl", "pt", "ro", "ru", "sk", "sl", "sq", "sr",
        "sv", "tr", "uk", "uz", "vi",
    }
)  # fmt: skip
#: Regions of those languages that write a decimal point.
_POINT_REGIONS: Final = frozenset(
    {"de-ch", "de-li", "it-ch", "es-mx", "es-us", "es-pr", "es-do", "es-gt", "es-hn", "es-ni",
     "es-pa", "es-sv", "fr-ca"}
)  # fmt: skip


def words(text: str) -> list[str]:
    """The words of a class name, an id, a heading: ``"team-card__photo"`` → team, card, photo."""
    spaced = _CAMEL.sub(" ", text)
    return [w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if w]


def is_utility_class(token: str) -> bool:
    """A framework utility (``col-md-4``, ``py-5``, ``text-muted``, ``md:w-1/2``) or a state."""
    lowered = token.lower()
    if any(char in lowered for char in ":/[]!@") or _DIGIT.search(lowered):
        return True
    return bool(_UTILITY.match(lowered))


def semantic_classes(node: Node, source: str) -> list[str]:
    """The node's class tokens that name what it is, not how it looks."""
    return [token for token in node.classes(source) if not is_utility_class(token)]


def snake(text: str) -> str:
    """``"Key services"`` → ``key_services``. Never empty, never starts with a digit."""
    parts = words(text)
    name = "_".join(parts) or "field"
    return f"f_{name}" if name[0].isdigit() else name


def pascal(text: str) -> str:
    """``"menu section"`` → ``MenuSection``."""
    name = "".join(part.capitalize() for part in words(text)) or "Item"
    return f"M{name}" if name[0].isdigit() else name


def singular(word: str) -> str:
    """English plural endings removed: ``categories`` → category, ``classes`` → class."""
    lower = word.lower()
    if len(lower) <= 3 or lower.endswith(("ss", "us", "is")):
        return word
    if lower.endswith("ies"):
        return word[:-3] + "y"
    if lower.endswith(("ches", "shes", "xes", "sses", "zes")):
        return word[:-2]
    if lower.endswith("s"):
        return word[:-1]
    return word


def plural(word: str) -> str:
    """``category`` → categories, ``class`` → classes, ``fact`` → facts, ``related`` as is."""
    lower = word.lower()
    if lower.endswith("s") and not lower.endswith("ss"):
        return word
    if lower.endswith(("ed", "ing", "ful", "ous", "ive", "al")):
        return word  # an adjective or a participle names a list as it is
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return word[:-1] + "ies"
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def slugify(text: str, max_length: int = 50) -> str:
    """A URL slug (ASCII letters, digits and hyphens), at most ``max_length`` characters."""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_JOIN.sub("-", _SLUG_DROP.sub("", normalized.lower())).strip("-_")
    if len(slug) > max_length:
        cut = slug[:max_length]
        slug = cut.rsplit("-", 1)[0] if "-" in cut[max_length // 2 :] else cut
    return slug.strip("-")


def highlight_spec(node: Node, source: str) -> str:
    """How an inline element is written: ``em``, ``span.accent``, ``strong.text-primary``."""
    classes = node.classes(source)
    return node.tag + "".join(f".{name}" for name in classes)


def _emphasis(child: Node, parent_text: str, source: str) -> bool:
    """``child`` sets some words of its parent apart: an emphasis element with text, not all."""
    if child.tag not in EMPHASIS:
        return False
    inner = child.plain_text(source)
    return bool(inner) and inner != parent_text


def mark_pattern(marker: str = HIGHLIGHT_MARKER) -> re.Pattern[str]:
    """The words between two markers that no backslash escapes: ``==words==``."""
    escaped = re.escape(marker)
    return re.compile(rf"(?<!\\){escaped}(.+?)(?<!\\){escaped}", re.DOTALL)


def unmark(text: str, marker: str = HIGHLIGHT_MARKER) -> str:
    """``text`` without its highlight marks: the words, a ``\\==`` as ``==``."""
    return mark_pattern(marker).sub(r"\1", text).replace("\\" + marker, marker)


def text_of(
    node: Node,
    source: str,
    *,
    highlight: bool = True,
    drop: Iterable[str] = (),
    marker: str = HIGHLIGHT_MARKER,
) -> tuple[str, list[str]]:
    """The text of ``node`` and the highlight markup found in it.

    With ``highlight``, highlighted words (an emphasis element holding part
    of the text) go between two ``marker`` (``==words==``), and a marker the
    text itself holds is written with a backslash before it (``\\==``).
    ``<br>`` becomes a line break and every other run of whitespace one space.
    Elements written as one of ``drop`` (``span.arrow``) are left out:
    decoration every item has.
    """
    dropped = set(drop)
    whole = node.plain_text(source)
    found: list[str] = []
    pieces: list[str] = []

    def literal(text: str) -> str:
        return text.replace(marker, "\\" + marker) if highlight and marker else text

    def walk(current: Node) -> None:
        for child in current.children:
            if child.kind == "text":
                pieces.append(literal(unescape(child.text(source))))
            elif child.kind == "element":
                if dropped and highlight_spec(child, source) in dropped:
                    continue
                if child.tag == "br":
                    pieces.append("\n")
                elif highlight and current is node and _emphasis(child, whole, source):
                    inner = literal(child.plain_text(source))
                    pieces.append(f"{marker}{inner}{marker}")
                    spec = highlight_spec(child, source)
                    if spec not in found:
                        found.append(spec)
                elif child.tag in ("script", "style", "template", "svg"):
                    continue
                else:
                    walk(child)

    walk(node)
    joined = "".join(pieces)
    lines = [collapse(line) for line in joined.split("\n")]
    text = "\n".join(line for line in lines if line) if len(lines) > 1 else lines[0]
    return text.strip(), found


def page_language(document: Any, source: str) -> str:
    """The ``lang`` of a page's ``<html>`` (``"de-CH"``), or ``""``."""
    root = getattr(document, "root", None)
    if root is None:
        return ""
    html = next(iter(root.find_all("html")), None)
    return str(html.attr(source, "lang") or "").strip() if html is not None else ""


def decimal_mark(language: str | None) -> str | None:
    """``","`` for a language that writes ``4,5``, ``"."`` for one that writes ``4.5``.

    ``None`` when the page says no language: a number is then read the
    English way, with a lone ``,`` before three digits a thousands separator.
    """
    tag = (language or "").strip().lower().replace("_", "-")
    if not tag:
        return None
    if tag in _POINT_REGIONS or "-".join(tag.split("-")[:2]) in _POINT_REGIONS:
        return "."
    return "," if tag.split("-")[0] in _COMMA_LANGUAGES else "."


def _decimal(raw: str, decimal: str | None) -> Decimal:
    """The digits of ``raw`` as a Decimal: group separators dropped, the decimal mark a point."""
    sign = raw[0] if raw[:1] in "+-" else ""
    body = raw[len(sign) :]
    marks = [(index, char) for index, char in enumerate(body) if not char.isdigit()]
    if not marks:
        return Decimal(sign + body)
    kinds = {char for _, char in marks}
    last_index, last = marks[-1]
    tail = body[last_index + 1 :]
    if len(kinds) > 1:
        point = last if last in ".," else ""  # 1.234,5 and 1,234.5: the last one
    elif len(marks) > 1 or last not in ".,":
        point = ""  # 1,234,567, 1 234, 1'234: groups only
    elif len(tail) != 3:
        point = last  # 4,5 or 4.25: a decimal, whatever the language
    else:  # 4,000 or 4.000: the language decides, English by default
        point = last if last == (decimal or ".") else ""
    digits = "".join(
        "." if index == last_index and point else char
        for index, char in enumerate(body)
        if char.isdigit() or (index == last_index and point)
    )
    return Decimal(sign + digits)


def number(text: str, decimal: str | None = None) -> tuple[Decimal, str, str] | None:
    """``"12 weeks"`` → (12, "", " weeks"). ``None`` unless the text is one number and a unit.

    ``decimal`` is the page's decimal mark (:func:`decimal_mark`): it
    decides only a lone separator before exactly three digits, ``"4,000"``
    (4000, or 4.0 where a comma is the decimal mark).
    """
    match = _NUMBER.match(text.strip())
    if match is None:
        return None
    try:
        value = _decimal(match.group("value"), decimal)
    except InvalidOperation:
        return None
    return value, match.group("before"), match.group("after")


def price(text: str) -> tuple[Decimal, str, str] | None:
    """``"€4.50"``, ``"From $12"``, ``"4,50 €"`` → (amount, currency code, text around it)."""
    match = _PRICE.match(text.strip())
    if match is None:
        return None
    symbol = match.group("cur1") or match.group("cur2")
    if not symbol:
        return None
    code = _CURRENCIES.get(symbol, symbol)
    raw = match.group(3)
    decimals = re.search(r"[.,](\d{1,2})$", raw)
    if decimals:
        amount = re.sub(r"[ ,.]", "", raw[: decimals.start()]) + "." + decimals.group(1)
    else:
        amount = re.sub(r"[ ,.]", "", raw)
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return None
    around = (match.group("before") + "|" + match.group("after")).strip()
    return value, code, around


def date(text: str) -> Date | None:
    """``"14 March 2026"``, ``"March 14, 2026"`` or ``"2026-03-14"`` as a date, else ``None``."""
    cleaned = collapse(text)
    try:
        iso = _ISO_DATE.match(cleaned)
        if iso and len(cleaned) in (10, 16, 19, 20, 25):
            return Date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        match = _DAY_MONTH_YEAR.match(cleaned)
        if match:
            month = _MONTHS.get(match.group(2).lower())
            if month:
                return Date(int(match.group(3)), month, int(match.group(1)))
        match = _MONTH_DAY_YEAR.match(cleaned)
        if match:
            month = _MONTHS.get(match.group(1).lower())
            if month:
                return Date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None
    return None

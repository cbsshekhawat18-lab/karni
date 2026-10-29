"""Opening hours in a design's markup: what ``karni import design --editable`` makes ``site.hours``.

A business's pages often show its opening hours twice, in the footer and on
the contact page, each in its own format. Kept as text blocks, the client
would type every change twice. The import finds the clear cases and makes
each a loop over ``site.hours`` (the site's opening hours rows), seeded once
from the design's own text with ``{% site_defaults hours="..." %}``:

* a table whose rows are two cells, the days and the times;
* a definition list, the days in ``<dt>`` and the times in ``<dd>``;
* a list whose items are each one line of days and times;
* an element whose lines (``<br>`` between them) are each days and times.

Every row must read as days (``Monday to Friday``, ``Mon–Fri``, ``Sat, Sun``,
``Montag bis Freitag``) and then times (``8:00 to 18:00``, ``9am - 5.30pm``,
``9:00–12:00, 14:00–18:00``) or a word for closed. Day names and the words
for closed are read in English, German, French, Spanish, Italian, Dutch
and Portuguese. A list where one row does not read is left as it is.

:func:`find` reads one element, :func:`same_hours` says whether two lists
hold the same hours in different formats. Nothing here writes a file.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from html import unescape
from typing import Final

from karni_cli.design.parse import Node, collapse

__all__ = ["HoursList", "find", "read_line", "same_hours"]

#: Day names and abbreviations, by weekday (Monday is 0), in the languages read.
_DAYS: Final[tuple[tuple[str, ...], ...]] = (
    ("monday", "mon", "mo", "montag", "lundi", "lun", "lu", "lunes", "lunedi", "maandag", "ma",
     "segunda", "seg"),
    ("tuesday", "tue", "tues", "tu", "dienstag", "di", "mardi", "mar", "martes", "martedi",
     "dinsdag", "terca", "ter"),
    ("wednesday", "wed", "we", "mittwoch", "mi", "mercredi", "mer", "miercoles", "mie",
     "mercoledi", "woensdag", "wo", "quarta", "qua"),
    ("thursday", "thu", "thur", "thurs", "th", "donnerstag", "do", "jeudi", "jeu", "jueves",
     "jue", "giovedi", "gio", "donderdag", "quinta", "qui"),
    ("friday", "fri", "fr", "freitag", "vendredi", "ven", "viernes", "vie", "venerdi",
     "vrijdag", "vr", "sexta", "sex"),
    ("saturday", "sat", "sa", "samstag", "samedi", "sam", "sabado", "sab", "zaterdag", "za"),
    ("sunday", "sun", "su", "sonntag", "so", "dimanche", "dim", "domingo", "dom", "domenica",
     "zondag", "zo"),
)  # fmt: skip
_DAY_INDEX: Final[dict[str, int]] = {
    name: index for index, names in enumerate(_DAYS) for name in names
}
#: Words for every day, for the weekdays, for the weekend.
_SPANS: Final[dict[str, tuple[int, ...]]] = {
    "daily": tuple(range(7)),
    "every day": tuple(range(7)),
    "everyday": tuple(range(7)),
    "7 days": tuple(range(7)),
    "weekdays": tuple(range(5)),
    "weekends": (5, 6),
    "weekend": (5, 6),
    "taglich": tuple(range(7)),
    "werktags": tuple(range(5)),
    "tous les jours": tuple(range(7)),
    "todos los dias": tuple(range(7)),
    "tutti i giorni": tuple(range(7)),
    "dagelijks": tuple(range(7)),
}
_RANGE: Final = re.compile(r"\s*-\s*|\s+(?:to|till|until|through|thru|bis|a|au|al|tot|ate)\s+")
_LIST: Final = re.compile(r"\s*(?:,|&|\+|/)\s*|\s+(?:and|und|et|y|e|en)\s+")
_CLOSED: Final = re.compile(
    r"^(?:closed|geschlossen|ruhetag|ferme|fermee|cerrado|chiuso|gesloten|fechado)\b\.?$"
)
_TIME: Final = r"(?:\d{1,2}(?:[:.h]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|noon|midday|midnight)"
_SPAN: Final = rf"{_TIME}\s*(?:-|–|—|to|till|until|bis|a|à|au|tot)\s*{_TIME}(?:\s*(?:uhr|h))?"
_TIMES: Final = re.compile(rf"^{_SPAN}(?:\s*(?:,|&|and|und|et|y|/)\s*{_SPAN})*$")
_CELLS: Final = frozenset({"td", "th"})
_CLOCK: Final = re.compile(
    r"(?P<word>noon|midday|midnight)|(?P<hour>\d{1,2})(?:[:.h](?P<minute>\d{2}))?\s*"
    r"(?P<half>a\.?m\.?|p\.?m\.?)?"
)


def _plain(text: str) -> str:
    """Lowercase ASCII, dashes as ``-``, whitespace collapsed: ``"Mo–Fr"`` is ``"mo-fr"``."""
    dashed = text.replace("–", "-").replace("—", "-")
    folded = unicodedata.normalize("NFKD", dashed).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.lower().split())


def day_set(text: str) -> tuple[int, ...] | None:
    """The weekdays ``text`` names (``"Mon - Fri"`` is 0 to 4), or ``None`` when it is not days."""
    value = _plain(text).strip(" :.")
    if not value:
        return None
    if value in _SPANS:
        return _SPANS[value]
    found: list[int] = []
    for part in _LIST.split(value):
        if not part:
            continue
        ends = [end.strip(".") for end in _RANGE.split(part)]
        if len(ends) == 1:
            if ends[0] not in _DAY_INDEX:
                return None
            found.append(_DAY_INDEX[ends[0]])
            continue
        if len(ends) != 2 or ends[0] not in _DAY_INDEX or ends[1] not in _DAY_INDEX:
            return None
        first, last = _DAY_INDEX[ends[0]], _DAY_INDEX[ends[1]]
        found.extend(
            range(first, last + 1) if first <= last else [*range(first, 7), *range(last + 1)]
        )
    return tuple(dict.fromkeys(found)) or None


def times_key(text: str) -> tuple[str, ...] | None:
    """What ``text`` says of the times, comparable across formats, or ``None`` when it is not."""
    value = _plain(text).strip(" .")
    if _CLOSED.match(value):
        return ("closed",)
    if not _TIMES.match(value):
        return None
    found: list[str] = []
    for match in _CLOCK.finditer(value):
        if match.group("word"):
            found.append("720" if match.group("word") in ("noon", "midday") else "0")
            continue
        hour, minute = int(match.group("hour")), int(match.group("minute") or 0)
        half = (match.group("half") or "").replace(".", "")
        if half == "pm" and hour < 12:
            hour += 12
        elif half == "am" and hour == 12:
            hour = 0
        found.append(str(hour * 60 + minute))
    return tuple(found)


def read_line(text: str) -> tuple[str, str] | None:
    """``"Mon–Fri 8:00–18:00"`` as ``("Mon–Fri", "8:00–18:00")``: the days, then the times."""
    line = collapse(unescape(text)).strip()
    if not line:
        return None
    words = line.split(" ")
    for cut in range(len(words) - 1, 0, -1):
        days = " ".join(words[:cut]).rstrip(":,")
        times = " ".join(words[cut:]).lstrip(":- ")
        if day_set(days) is not None and times_key(times) is not None:
            return days, times
    return None


@dataclass
class HoursList:
    """An element of a page that shows opening hours, and how its markup holds them."""

    node: Node
    kind: str  # "table", "dl", "list" or "lines"
    rows: list[tuple[str, str]]
    #: The element of each row (a ``<tr>``, an ``<li>``; the ``<dt>`` for a ``dl``).
    items: list[Node] = field(default_factory=list)
    #: Per row, the elements that hold the days and the times (cells, ``dt`` and ``dd``).
    cells: list[tuple[Node, Node]] = field(default_factory=list)

    @property
    def explicit(self) -> int:
        """How clearly the markup parts days from times: cells first, lines last."""
        return {"table": 3, "dl": 3, "list": 2, "lines": 1}[self.kind]


def _text(node: Node, source: str) -> str:
    return node.plain_text(source)


def _cells(row: Node) -> list[Node]:
    return [child for child in row.elements() if child.tag in _CELLS]


def _table(node: Node, source: str) -> HoursList | None:
    rows = [tr for tr in node.iter_elements() if tr.tag == "tr"]
    if len(rows) < 2:
        return None
    found = HoursList(node, "table", [])
    for row in rows:
        cells = _cells(row)
        if len(cells) != 2:
            return None
        days, times = _text(cells[0], source), _text(cells[1], source)
        if day_set(days) is None or times_key(times) is None:
            return None
        found.rows.append((days, times))
        found.items.append(row)
        found.cells.append((cells[0], cells[1]))
    return found


def _dl(node: Node, source: str) -> HoursList | None:
    children = list(node.elements())
    if (
        len(children) < 4
        or len(children) % 2
        or any(
            child.tag != ("dt" if index % 2 == 0 else "dd") for index, child in enumerate(children)
        )
    ):
        return None
    found = HoursList(node, "dl", [])
    for term, value in zip(children[::2], children[1::2], strict=True):
        days, times = _text(term, source), _text(value, source)
        if day_set(days) is None or times_key(times) is None:
            return None
        found.rows.append((days, times))
        found.items.append(term)
        found.cells.append((term, value))
    return found


def _list(node: Node, source: str) -> HoursList | None:
    items = list(node.elements())
    if len(items) < 2 or any(item.tag != "li" for item in items):
        return None
    found = HoursList(node, "list", [])
    for item in items:
        if any(child.kind == "element" for child in item.children):
            return None  # markup inside an item: not a plain line
        line = read_line(_text(item, source))
        if line is None:
            return None
        found.rows.append(line)
        found.items.append(item)
    return found


def _lines(node: Node, source: str) -> HoursList | None:
    parts: list[str] = [""]
    for child in node.children:
        if child.kind == "text":
            parts[-1] += child.text(source)
        elif child.kind == "element" and child.tag == "br":
            parts.append("")
        else:
            return None  # other markup: not lines of text
    lines = [line for line in parts if line.strip()]
    if len(lines) < 2 or len(lines) != len(parts):
        return None
    found = HoursList(node, "lines", [])
    for text in lines:
        line = read_line(text)
        if line is None:
            return None
        found.rows.append(line)
    return found


def find(node: Node, source: str) -> HoursList | None:
    """The opening hours ``node`` shows, when it is one of the clear cases (see the module)."""
    if node.kind != "element":
        return None
    if node.tag == "table":
        return _table(node, source)
    if node.tag in ("tbody", "thead"):
        return None
    if node.tag == "dl":
        return _dl(node, source)
    if node.tag in ("ul", "ol"):
        return _list(node, source)
    if node.tag in ("p", "div", "address", "span", "small"):
        return _lines(node, source)
    return None


def same_hours(first: HoursList, second: HoursList) -> bool:
    """Whether two lists show the same hours, however each writes them."""
    if len(first.rows) != len(second.rows):
        return False
    for (days_a, times_a), (days_b, times_b) in zip(first.rows, second.rows, strict=True):
        if day_set(days_a) != day_set(days_b) or times_key(times_a) != times_key(times_b):
            return False
    return True

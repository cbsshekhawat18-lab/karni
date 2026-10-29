"""The site's structured data: who runs it, as schema.org JSON-LD, from the site's settings.

:func:`build` is ``KARNI_SITE_JSONLD``'s default. ``{% karni_seo %}`` puts
its result in every page's head as ``<script type="application/ld+json">``:
a ``WebSite`` and an ``Organization`` (or ``LocalBusiness``, or the type
``KARNI_SITE_SCHEMA_TYPE`` names) with the site's name, address, logo,
share image, phone, email, map link, social profiles (``sameAs``) and, for
a business, its opening hours.

Opening hours are written as the site shows them ("Mon to Fri",
"9:00 to 17:00"). :func:`opening_hours` reads English day names and
abbreviations, ranges ("Mon - Fri", "Monday to Friday"), lists ("Sat, Sun"),
"daily" and "weekdays", and times in 24 or 12 hour form ("9am - 5.30pm").
A line it cannot read, or "closed", is left out rather than guessed.

Override / escape hatch: ``KARNI_SITE_SCHEMA_TYPE`` (``None`` for no
JSON-LD), or ``KARNI_SITE_JSONLD`` naming your own
``(request, site) -> dict | None`` function, which can call :func:`build`
and add to its result.
"""

from __future__ import annotations

import re
from typing import Any

from django.db.models.fields.files import FieldFile

from karni_site import conf

__all__ = ["build", "opening_hours", "parse_days", "parse_times", "schema_type"]

_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_DAY = re.compile(
    r"^(mo|mon|monday|tu|tue|tues|tuesday|we|wed|weds|wednesday|th|thu|thur|thurs|thursday|"
    r"fr|fri|friday|sa|sat|saturday|su|sun|sunday)\.?$"
)
_RANGE = re.compile(r"\s*(?:-|–|—|to|till|until|through|thru)\s*")
_LIST = re.compile(r"\s*(?:,|&|\+|/|\band\b)\s*")
_TIME = re.compile(
    r"^(?:(?P<word>noon|midday|midnight)|(?P<hour>\d{1,2})(?:[:.h](?P<minute>\d{2}))?\s*"
    r"(?P<half>a\.?m\.?|p\.?m\.?)?)$"
)
_ALL_WEEK = frozenset({"daily", "every day", "everyday", "all week", "7 days", "seven days"})


def schema_type(site: Any) -> str | None:
    """The schema.org type for the site: ``KARNI_SITE_SCHEMA_TYPE``, ``"auto"`` decided here."""
    configured = conf.get("KARNI_SITE_SCHEMA_TYPE")
    if not configured:
        return None
    if str(configured) != "auto":
        return str(configured)
    return "LocalBusiness" if list(getattr(site, "hours", None) or []) else "Organization"


def _day_index(word: str) -> int | None:
    match = _DAY.match(word.strip().lower())
    if match is None:
        return None
    return next(
        i for i, name in enumerate(_DAY_NAMES) if name.lower().startswith(match.group(1)[:2])
    )


def parse_days(text: str) -> list[str] | None:
    """``"Mon to Fri"`` as ``["Monday", ..., "Friday"]``, or ``None`` when it is not days."""
    value = " ".join(text.lower().split())
    if value in _ALL_WEEK:
        return list(_DAY_NAMES)
    if value in ("weekdays", "week days", "monday to friday"):
        return list(_DAY_NAMES[:5])
    if value in ("weekends", "weekend"):
        return list(_DAY_NAMES[5:])
    found: list[str] = []
    for part in _LIST.split(value):
        if not part:
            continue
        ends = _RANGE.split(part)
        if len(ends) == 1:
            index = _day_index(ends[0])
            if index is None:
                return None
            found.append(_DAY_NAMES[index])
            continue
        if len(ends) != 2:
            return None
        first, last = _day_index(ends[0]), _day_index(ends[1])
        if first is None or last is None:
            return None
        span = range(first, last + 1) if first <= last else [*range(first, 7), *range(0, last + 1)]
        found.extend(_DAY_NAMES[i] for i in span)
    return list(dict.fromkeys(found)) or None


def _time(text: str) -> str | None:
    match = _TIME.match(text.strip().lower().replace(" ", ""))
    if match is None:
        return None
    if match.group("word"):
        return "12:00" if match.group("word") in ("noon", "midday") else "00:00"
    hour, minute = int(match.group("hour")), int(match.group("minute") or 0)
    half = (match.group("half") or "").replace(".", "")
    if half == "pm" and hour < 12:
        hour += 12
    elif half == "am" and hour == 12:
        hour = 0
    if hour > 24 or minute > 59:
        return None
    return f"{hour % 24:02d}:{minute:02d}" if hour != 24 else "23:59"


def parse_times(text: str) -> list[tuple[str, str]] | None:
    """``"9:00 to 17:00"`` as ``[("09:00", "17:00")]``. ``[]`` for closed, ``None`` unread."""
    value = " ".join(text.lower().split())
    if not value:
        return None
    if value.startswith("closed"):
        return []
    if value in ("24 hours", "open 24 hours", "24/7", "all day"):
        return [("00:00", "23:59")]
    found: list[tuple[str, str]] = []
    for part in re.split(r"\s*(?:,|&|\band\b)\s*", value):
        ends = _RANGE.split(part, maxsplit=1)
        if len(ends) != 2:
            return None
        opens, closes = _time(ends[0]), _time(ends[1])
        if opens is None or closes is None:
            return None
        found.append((opens, closes))
    return found or None


def opening_hours(rows: Any) -> list[dict[str, Any]]:
    """``OpeningHoursSpecification`` entries for the site's opening hours rows it can read."""
    found: list[dict[str, Any]] = []
    for row in rows or ():
        days_text = str(getattr(row, "days", "") or "")
        times_text = str(getattr(row, "times", "") or "")
        if not times_text:
            split = re.search(r"\d|closed|noon|midnight", days_text.lower())
            if split is None:
                continue
            days_text, times_text = days_text[: split.start()], days_text[split.start() :]
        days = parse_days(days_text.strip(" :"))
        times = parse_times(times_text)
        if not days or not times:
            continue
        for opens, closes in times:
            found.append(
                {
                    "@type": "OpeningHoursSpecification",
                    "dayOfWeek": days if len(days) > 1 else days[0],
                    "opens": opens,
                    "closes": closes,
                }
            )
    return found


def _file_url(value: Any, request: Any) -> str:
    from karni_site.metadata import absolute

    if isinstance(value, FieldFile):
        if not value.name:
            return ""
        try:
            return absolute(str(value.url), request)
        except ValueError:
            return ""
    return ""


def build(request: Any, site: Any) -> dict[str, Any] | None:
    """The site's JSON-LD: a ``WebSite`` and who runs it. ``None`` without a name or a type."""
    from karni_site.metadata import site_url

    kind = schema_type(site)
    name = str(getattr(site, "name", "") or "").strip()
    if kind is None or not name:
        return None
    root = site_url(request) + "/"
    who: dict[str, Any] = {"@type": kind, "@id": f"{root}#organization", "name": name, "url": root}
    tagline = str(getattr(site, "tagline", "") or "").strip()
    if tagline:
        who["description"] = tagline
    logo = _file_url(getattr(site, "logo", None), request)
    if logo:
        who["logo"] = logo
    image = _file_url(getattr(site, "share_image", None), request) or logo
    if image:
        who["image"] = image
    phone = str(getattr(site, "phone_link", "") or getattr(site, "phone", "") or "").strip()
    if phone:
        who["telephone"] = phone
    email = str(getattr(site, "email", "") or "").strip()
    if email:
        who["email"] = email
    lines = list(getattr(site, "address_lines", None) or [])
    if lines:
        who["address"] = {"@type": "PostalAddress", "streetAddress": ", ".join(lines)}
    map_url = str(getattr(site, "map_url", "") or "").strip()
    if map_url:
        who["hasMap"] = map_url
    profiles = [str(link.url) for link in getattr(site, "social_links", None) or [] if link.url]
    if profiles:
        who["sameAs"] = profiles
    if kind not in ("Organization", "Corporation", "NGO", "Person"):
        hours = opening_hours(getattr(site, "hours", None))
        if hours:
            who["openingHoursSpecification"] = hours
    website = {
        "@type": "WebSite",
        "@id": f"{root}#website",
        "name": name,
        "url": root,
        "publisher": {"@id": who["@id"]},
    }
    return {"@context": "https://schema.org", "@graph": [website, who]}

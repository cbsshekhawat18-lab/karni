"""The site's own details at render time: ``site`` in templates, and its defaults.

:func:`get_site_settings` returns the one row of the settings model
(``KARNI_SITE_SETTINGS_MODEL``) with its opening hours and social links,
from one cache entry. Without a row it returns an empty, unsaved one, so a
template never fails on ``{{ site.name }}``.

:func:`seed` is what ``{% site_defaults name="..." phone="..." %}`` calls:
a field the template gives a default for is filled the first time, and
keeps following the template's value until someone changes it in the
admin. ``seeded`` on the row records what each template gave.

``hours="Monday to Friday=8:00 to 18:00|Saturday=9:00 to 13:00|Sunday=Closed"``
seeds the opening hours rows (``site.hours``): each ``|`` a row, its days
before ``=`` and its times after. They are added when the site has none, and
follow the template while they are as it gave them. Once the client changes
them, theirs stay, and hours a client deleted are not added again.

An image field (``logo``, ``favicon``, ``share_image``, or any file field of
the settings model) takes a static path as its default:
``{% site_defaults share_image="website/img/share.jpg" %}``. The file field
stays empty, and :func:`image_url` gives the uploaded file's address, else
that static file's, until the client uploads one.

Override / escape hatch: ``KARNI_SITE_SETTINGS_MODEL`` swaps the model,
``KARNI_SITE_SEED_ON_RENDER = False`` stores nothing while a page renders.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from django.apps import apps
from django.db import DatabaseError, IntegrityError, models, transaction
from karni.exceptions import KarniImproperlyConfigured

from karni_site import caching, conf

__all__ = [
    "HOURS",
    "SEEDABLE",
    "hours_rows",
    "file_fields",
    "forget",
    "get_site_settings",
    "image_url",
    "seed",
    "settings_model",
    "social_name",
]

logger = logging.getLogger("karni_site")
MODEL_CODE = "SITE009"

#: The fields ``{% site_defaults %}`` may give a default for (plus ``social_<name>``).
SEEDABLE = ("name", "tagline", "address", "phone", "phone_link", "email", "map_url")
#: ``{% site_defaults hours="..." %}``: the opening hours rows, not a field of the row.
HOURS = "hours"
#: How a social network's slug is written as a name.
_SOCIAL_NAMES = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "github": "GitHub",
    "gitlab": "GitLab",
    "x": "X",
    "twitter": "Twitter",
    "pinterest": "Pinterest",
    "threads": "Threads",
    "mastodon": "Mastodon",
    "bluesky": "Bluesky",
    "whatsapp": "WhatsApp",
    "vimeo": "Vimeo",
    "behance": "Behance",
    "dribbble": "Dribbble",
    "tripadvisor": "Tripadvisor",
    "yelp": "Yelp",
    "houzz": "Houzz",
}


def settings_model() -> type[models.Model]:
    """The model ``KARNI_SITE_SETTINGS_MODEL`` names."""
    label = str(conf.get("KARNI_SITE_SETTINGS_MODEL"))
    try:
        return apps.get_model(label, require_ready=False)
    except (ValueError, LookupError) as exc:
        raise KarniImproperlyConfigured(
            f"KARNI_SITE_SETTINGS_MODEL is {label!r}, which is not an installed model "
            "('app_label.ModelName', a subclass of karni_site.models.AbstractSiteSettings).",
            code=MODEL_CODE,
        ) from exc


def file_fields() -> set[str]:
    """The file fields of the settings model: ``logo``, ``favicon``, ``share_image`` and any own."""
    model = settings_model()
    return {f.name for f in model._meta.get_fields() if isinstance(f, models.FileField)}


def image_url(site: Any, field: str) -> str:
    """The address of the site's ``field`` image: the upload, else the template's default.

    The default is the static path ``{% site_defaults %}`` gave (through
    ``static()``, so a hashed name in production), else the address the
    design's markup showed (``{% site_image %}``). ``""`` when there is none.
    """
    stored = getattr(site, field, None)
    try:
        if stored:
            return str(stored.url)
    except ValueError:
        pass
    seeded = getattr(site, "seeded", None) or {}
    path = str((seeded.get("static") or {}).get(field) or "")
    if path:
        if path.startswith(("/", "http://", "https://")):
            return path
        from django.templatetags.static import static

        try:
            return str(static(path))
        except ValueError:  # not in the manifest yet (collectstatic not run)
            logger.warning("karni_site: the default %s %r is not a static file", field, path)
            return ""
    return str((seeded.get("images") or {}).get(field) or "")


def social_name(slug: str) -> str:
    """``"linkedin"`` as ``"LinkedIn"``: the name a seeded social link gets."""
    return _SOCIAL_NAMES.get(slug, slug.replace("_", " ").title())


def _key() -> str:
    return caching.key("settings")


def _load() -> Any:
    model = settings_model()
    row = model._default_manager.first()
    if row is None:
        return model()
    row.__dict__["_karni_hours"] = list(row.opening_hours_rows.all())
    row.__dict__["_karni_social"] = list(row.social_link_rows.all())
    return row


def get_site_settings() -> Any:
    """The site's settings row (cached), or an empty unsaved one."""
    store = caching.cache()
    found = store.get(_key())
    if found is None:
        try:
            found = _load()
        except DatabaseError:
            logger.exception("karni_site: the site settings could not be read")
            return settings_model()()
        store.set(_key(), found, caching.timeout())
    return found


def forget() -> None:
    """Drop the cached settings (the row, its hours or its social links changed)."""
    caching.cache().delete(_key())


def _plan(current: Any, defaults: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The field changes and the new ``seeded`` record ``defaults`` call for."""
    seeded: dict[str, Any] = dict(current.seeded or {})
    changes: dict[str, Any] = {}
    files = file_fields()
    static = dict(seeded.get("static") or {})
    for field, value in defaults.items():
        if field in files:
            static[field] = value  # a default address only: the file field stays the client's
            continue
        if field.startswith("social_") or field in ("images", HOURS):
            continue
        now = getattr(current, field, "") or ""
        if field not in seeded:
            if not now:
                changes[field] = value
            seeded[field] = value
        elif seeded[field] != value:
            if now == seeded[field]:
                changes[field] = value  # nobody changed it: it follows the template
            seeded[field] = value
    social = dict(seeded.get("social") or {})
    for field, value in defaults.items():
        if field.startswith("social_"):
            social[field.removeprefix("social_")] = value
    if social:
        seeded["social"] = social
    images = dict(seeded.get("images") or {})
    given = defaults.get("images")
    if isinstance(given, Mapping):
        images.update(given)
    if images:
        seeded["images"] = images
    if static:
        seeded["static"] = static
    if HOURS in defaults:
        seeded[HOURS] = str(defaults[HOURS])
    return changes, seeded


def seed(defaults: Mapping[str, Any]) -> Any | None:
    """Store the template's defaults for the site's details. The fresh row, or ``None``.

    ``None`` (the usual case, after the first render) means nothing changed
    and nothing was written.
    """
    if not conf.get("KARNI_SITE_SEED_ON_RENDER"):
        return None
    current = get_site_settings()
    changes, seeded = _plan(current, defaults)
    if not changes and seeded == (current.seeded or {}) and current.pk is not None:
        return None
    model = settings_model()
    try:
        with transaction.atomic():
            row = model._default_manager.select_for_update().first()
            if row is None:
                row = model()
            changes, seeded = _plan(row, defaults)
            old_social = dict((row.seeded or {}).get("social") or {})
            old_hours = (row.seeded or {}).get(HOURS)
            for field, value in changes.items():
                setattr(row, field, value)
            row.seeded = seeded
            row.save()
            _seed_social(row, old_social, dict(seeded.get("social") or {}))
            if HOURS in defaults:
                _seed_hours(row, old_hours, str(defaults[HOURS]))
    except IntegrityError:
        forget()
        return None
    except DatabaseError:
        logger.exception("karni_site: the site's defaults could not be stored")
        return None
    forget()
    return get_site_settings()


def hours_rows(text: str) -> list[tuple[str, str]]:
    """``"Mon to Fri=9:00 to 17:00|Sun=Closed"`` as ``[(days, times), ...]``."""
    found: list[tuple[str, str]] = []
    for part in str(text or "").split("|"):
        days, _sep, times = part.partition("=")
        if days.strip():
            found.append((" ".join(days.split()), " ".join(times.split())))
    return found


def _seed_hours(row: Any, before: str | None, after: str) -> None:
    """The template's opening hours, unless the client has their own (or deleted them)."""
    from karni_site.models import OpeningHours

    existing = [(h.days, h.times) for h in OpeningHours.objects.filter(site=row)]
    wanted = hours_rows(after)
    if before is None:
        if existing:
            return  # entered before the template gave any: the client's
    elif existing != hours_rows(before) or not existing:
        return  # changed or deleted in the admin: theirs stay
    if existing == wanted:
        return
    OpeningHours.objects.filter(site=row).delete()
    for order, (days, times) in enumerate(wanted):
        OpeningHours.objects.create(site=row, days=days, times=times, order=order)


def _seed_social(row: Any, before: Mapping[str, str], after: Mapping[str, str]) -> None:
    """A social link per new ``social_<name>`` default. One a client removed stays removed."""
    from karni_site.models import SocialLink

    existing = {link.slug: link for link in SocialLink.objects.filter(site=row)}
    order = len(existing)
    for slug, url in after.items():
        if slug in before:
            link = existing.get(slug)
            if link is not None and link.url == before[slug] and url != before[slug]:
                link.url = url
                link.save()
            continue
        if slug not in existing:
            SocialLink.objects.create(site=row, name=social_name(slug), url=url, order=order)
            order += 1

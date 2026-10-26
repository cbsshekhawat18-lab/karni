"""The site's own details at render time: ``site`` in templates, and its defaults.

:func:`get_site_settings` returns the one row of the settings model
(``KARNI_SITE_SETTINGS_MODEL``) with its opening hours and social links,
from one cache entry. Without a row it returns an empty, unsaved one, so a
template never fails on ``{{ site.name }}``.

:func:`seed` is what ``{% site_defaults name="..." phone="..." %}`` calls:
a field the template gives a default for is filled the first time, and
keeps following the template's value until someone changes it in the
admin. ``seeded`` on the row records what each template gave.

Override / escape hatch: ``KARNI_SITE_SETTINGS_MODEL`` swaps the model,
``KARNI_SITE_SEED_ON_RENDER = False`` stores nothing while a page renders.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, IntegrityError, models, transaction

from karni_site import caching, conf

__all__ = [
    "SEEDABLE",
    "forget",
    "get_site_settings",
    "seed",
    "settings_model",
    "social_name",
]

logger = logging.getLogger("karni_site")

#: The fields ``{% site_defaults %}`` may give a default for (plus ``social_<name>``).
SEEDABLE = ("name", "tagline", "address", "phone", "phone_link", "email", "map_url")
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
        raise ImproperlyConfigured(
            f"KARNI_SITE_SETTINGS_MODEL is {label!r}, which is not an installed model "
            "('app_label.ModelName', a subclass of karni_site.models.AbstractSiteSettings)."
        ) from exc


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
    for field, value in defaults.items():
        if field.startswith("social_") or field == "images":
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
            for field, value in changes.items():
                setattr(row, field, value)
            row.seeded = seeded
            row.save()
            _seed_social(row, old_social, dict(seeded.get("social") or {}))
    except IntegrityError:
        forget()
        return None
    except DatabaseError:
        logger.exception("karni_site: the site's defaults could not be stored")
        return None
    forget()
    return get_site_settings()


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

"""Editable blocks at render time: what ``{% editable %}`` and ``{% editable_image %}`` show.

A block is looked up by key. Its page's blocks are one cache entry
(``karni_site:blocks:<page>``), read once per request, so a page with fifty
blocks costs one cache read. A key the database does not hold yet is
stored from the template's default on its first render. A block nobody
changed follows the template: when the template's default changes, the
stored default changes with it. A block someone changed keeps their text.

Rendering never fails because of the database: when it cannot be read, the
template's default is shown and the error logged (logger ``karni_site``).

Override / escape hatch: ``KARNI_SITE_SEED_ON_RENDER = False`` stores
nothing while a page renders (load blocks with ``karni load`` instead), and
``KARNI_SITE_CACHE`` / ``KARNI_SITE_CACHE_TIMEOUT`` choose the cache.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from typing import Any

from django.db import DatabaseError, IntegrityError, transaction

from karni_site import caching, conf
from karni_site.images import img_attributes, replace_image

__all__ = ["Stored", "forget", "image", "load_page", "text"]

logger = logging.getLogger("karni_site")
_MEMO = "_karni_site_blocks"


@dataclass(frozen=True)
class Stored:
    """What the cache keeps of one block."""

    kind: str
    html: str
    default_html: str
    image_url: str
    alt: str
    default_alt: str
    default_src: str

    @property
    def text_edited(self) -> bool:
        return self.html != self.default_html

    @property
    def alt_edited(self) -> bool:
        return self.alt != self.default_alt


def _page_key(page: str) -> str:
    return caching.key("blocks", page)


def _stored(block: Any) -> Stored:
    try:
        url = block.image.url if block.image else ""
    except ValueError:
        url = ""
    return Stored(
        kind=block.kind,
        html=block.html,
        default_html=block.default_html,
        image_url=url,
        alt=block.alt,
        default_alt=block.default_alt,
        default_src=block.default_src,
    )


def load_page(page: str) -> dict[str, Stored]:
    """Every block of ``page`` by key, from the cache or one query."""
    store = caching.cache()
    found: dict[str, Stored] | None = store.get(_page_key(page))
    if found is None:
        from karni_site.models import Block

        found = {block.key: _stored(block) for block in Block.objects.filter(page=page)}
        store.set(_page_key(page), found, caching.timeout())
    return found


def forget(page: str) -> None:
    """Drop ``page``'s cached blocks (a block of it was saved or deleted)."""
    caching.cache().delete(_page_key(page))


def _blocks(page: str, request: Any) -> dict[str, Stored]:
    if request is None:
        return dict(load_page(page))
    memo: dict[str, dict[str, Stored]] | None = getattr(request, _MEMO, None)
    if memo is None:
        memo = {}
        try:
            setattr(request, _MEMO, memo)
        except AttributeError:
            return dict(load_page(page))
    if page not in memo:
        memo[page] = dict(load_page(page))
    return memo[page]


def _seeding() -> bool:
    return bool(conf.get("KARNI_SITE_SEED_ON_RENDER"))


def _create(key: str, page: str, **values: Any) -> Any:
    """Store a new block from the template's default. ``None`` when another request won."""
    from karni_site.models import Block

    try:
        with transaction.atomic():
            position = Block.objects.filter(page=page).count()
            return Block.objects.create(key=key, position=position, **values)
    except IntegrityError:
        return None


def _follow(key: str, **values: Any) -> Any:
    """The template's default changed and nobody edited the block: store the new default."""
    from karni_site.models import Block

    block = Block.objects.filter(key=key).first()
    if block is None:
        return None
    for name, value in values.items():
        setattr(block, name, value)
    block.save(update_fields=[*values, "updated_at"])
    return block


def text(key: str, default: str, request: Any = None) -> str:
    """The HTML a text block shows: the edited text, else the template's ``default``."""
    from karni_site.models import Block

    page = Block.page_of(key)
    try:
        blocks = _blocks(page, request)
        stored = blocks.get(key)
        if stored is None:
            if _seeding():
                created = _create(
                    key, page, kind=Block.Kind.TEXT, html=default, default_html=default
                )
                if created is not None:
                    blocks[key] = _stored(created)
            return default
        if stored.kind != Block.Kind.TEXT:
            logger.warning("karni_site: block %s is an image, used as text", key)
            return default
        if not stored.text_edited:
            if default != stored.default_html and _seeding():
                followed = _follow(key, html=default, default_html=default)
                if followed is not None:
                    blocks[key] = _stored(followed)
            return default
        return stored.html
    except DatabaseError:
        logger.exception("karni_site: block %s could not be read, the default is shown", key)
        return default


def image(key: str, default: str, request: Any = None, *, url: bool = False) -> str:
    """The design's image markup (or bare address, ``url=True``) with the uploaded picture."""
    from karni_site.models import Block

    page = Block.page_of(key)
    if url:
        src, alt = default.strip(), ""
    else:
        attrs = img_attributes(default)
        src, alt = attrs.get("src", ""), attrs.get("alt", "")
    try:
        blocks = _blocks(page, request)
        stored = blocks.get(key)
        if stored is None:
            if _seeding():
                created = _create(
                    key,
                    page,
                    kind=Block.Kind.IMAGE,
                    alt=alt,
                    default_alt=alt,
                    default_src=src[:500],
                )
                if created is not None:
                    blocks[key] = _stored(created)
            return default
        if stored.kind != Block.Kind.IMAGE:
            logger.warning("karni_site: block %s is text, used as an image", key)
            return default
        changes: dict[str, str] = {}
        if not stored.alt_edited and alt != stored.default_alt:
            changes.update(alt=alt, default_alt=alt)
        if src[:500] != stored.default_src:
            changes["default_src"] = src[:500]
        if changes and _seeding():
            followed = _follow(key, **changes)
            if followed is not None:
                stored = blocks[key] = _stored(followed)
        new_src = stored.image_url or None
        new_alt = stored.alt if stored.alt_edited else None
        if url:
            return escape(new_src) if new_src else default
        if new_src is None and new_alt is None:
            return default
        return replace_image(default, new_src, new_alt)
    except DatabaseError:
        logger.exception("karni_site: block %s could not be read, the default is shown", key)
        return default

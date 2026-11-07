"""What a save clears: the receivers that keep karni_site's cache true.

Every save and delete of a block clears its page's cached blocks, of the
site's settings (or a line of its hours, or a social link) the cached
settings, of a menu or an item every cached menu, of a redirect every
cached redirect answer, of a page SEO entry every cached SEO answer. A save
of any other model clears the menus only when a menu lists its rows. A soft
delete is a save, so it clears too.

Override / escape hatch: call :func:`karni_site.blocks.forget`,
:func:`karni_site.sitesettings.forget` or :func:`karni_site.caching.bump`
yourself after a bulk ``update()``, which sends no signal.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save

from karni_site import blocks, caching, menus, sitesettings

__all__ = ["connect"]


def _block_changed(sender: type[Any], instance: Any, **kwargs: Any) -> None:
    blocks.forget(instance.page or instance.page_of(instance.key))


def _settings_changed(sender: type[Any], **kwargs: Any) -> None:
    sitesettings.forget()


def _menus_changed(sender: type[Any], **kwargs: Any) -> None:
    caching.bump("menus")


def _redirects_changed(sender: type[Any], **kwargs: Any) -> None:
    caching.bump("redirects")


def _seo_changed(sender: type[Any], **kwargs: Any) -> None:
    caching.bump("seo")


def connect() -> None:
    from karni_site.models import Block, Menu, MenuItem, OpeningHours, PageSeo, Redirect, SocialLink

    receivers: list[tuple[Any, Any]] = [
        (_block_changed, Block),
        (_settings_changed, sitesettings.settings_model()),
        (_settings_changed, OpeningHours),
        (_settings_changed, SocialLink),
        (_menus_changed, Menu),
        (_menus_changed, MenuItem),
        (_redirects_changed, Redirect),
        (_seo_changed, PageSeo),
    ]
    for receiver, sender in receivers:
        for signal in (post_save, post_delete):
            signal.connect(
                receiver,
                sender=sender,
                dispatch_uid=f"karni_site:{receiver.__name__}:{sender._meta.label}",
            )
    for signal in (post_save, post_delete):
        signal.connect(menus.model_changed, dispatch_uid="karni_site:menus:model_changed")

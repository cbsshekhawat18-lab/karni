"""Template helpers of Karni's admin pages."""

from __future__ import annotations

from typing import Any

from django import template
from django.contrib.admin.templatetags.admin_modify import submit_row

register = template.Library()


@register.simple_tag(takes_context=True)
def karni_submit(context: template.Context) -> dict[str, Any]:
    """Django's ``submit_row`` flags (which Save buttons, Delete, Close) for the page's own bar.

    ``{% karni_submit as submit %}`` gives ``submit.show_save``,
    ``submit.show_save_and_continue``, ``submit.show_save_and_add_another``,
    ``submit.show_delete_link`` and the rest, computed from the user's
    permissions the way the stock bar does.
    """
    return dict(submit_row(context).flatten())

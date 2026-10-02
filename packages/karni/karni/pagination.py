"""Default pagination class used by Karni's DRF configuration."""

from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class KarniPageNumberPagination(PageNumberPagination):
    """Page-number pagination with a client-controllable, capped page size.

    The default page size comes from ``REST_FRAMEWORK["PAGE_SIZE"]`` (the
    ``KARNI_PAGE_SIZE`` environment variable, 50 by default). Clients may
    request a different size with the ``?page_size=`` query parameter, capped
    at :attr:`max_page_size`.

    Override / escape hatch: subclass this and point
    ``REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"]`` at your subclass in the
    project's ``settings.py``, or set ``pagination_class`` per view.
    """

    page_size_query_param = "page_size"
    max_page_size = 500

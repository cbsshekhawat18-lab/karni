"""The shop's settings: what a shop manager changes on the Settings page, without code.

Read one with ``preferences.value("shop.low_stock", 3)``. The defaults come from the
project's settings (``SHOP_LOW_STOCK`` and the others), so a project that never opens
Settings keeps them. The business's name, address and email sender are the Details
tab, and checkout's options are karni-commerce's Checkout tab.
"""

from __future__ import annotations

from django.conf import settings
from karni_commerce import preferences_seam as preferences
from pydantic import Field


def _number(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


@preferences.section("shop", title="Shop", change="role:shop-manager")
class ShopPreferences(preferences.Section):
    """The catalogue, the stock and the reviews."""

    low_stock: int = Field(
        default_factory=lambda: _number("SHOP_LOW_STOCK", 3),
        ge=0,
        le=10000,
        description="A product runs low at this many left (unless it has its own).",
    )
    show_stock_left: bool = Field(
        True,
        description='Shoppers see how many are left when it runs low ("Only 2 left").',
    )
    hide_sold_out: bool = Field(
        False, description="Sold out products leave the catalogue until they are back."
    )
    reviews_need_approval: bool = Field(
        default_factory=lambda: bool(_number("SHOP_REVIEWS_NEED_APPROVAL", 1)),
        description="A review shows once staff approve it.",
    )
    related_count: int = Field(
        default_factory=lambda: _number("SHOP_RELATED_COUNT", 4),
        ge=0,
        le=12,
        description="How many related products a product page shows.",
    )
    download_limit: int = Field(
        5,
        ge=1,
        le=100,
        description="How often a buyer may download a file they bought.",
    )
    download_days: int = Field(
        30,
        ge=0,
        le=3650,
        description="For how many days a download link works (0: always).",
    )

"""shop demo data for karni seed. Each seeder extends the one karni build writes in
shop/karni/seeds.py: steer a field's values here.

The categories, products and prices are invented. Replace CATALOG with your own, or load
real rows with an import.
"""

from collections import Counter
from decimal import Decimal
from typing import Any

import factory
from factory.fuzzy import FuzzyChoice
from karni.seeding import SeedContext, cycled
from shop.karni import seeds as karni

from shop.models import Category

# category -> (product name, price, description). Eight products each.
CATALOG: dict[str, list[tuple[str, str, str]]] = {
    "Kitchen": [
        (
            "Beech Wood Chopping Board",
            "34.00",
            "A thick beech board with a juice groove, oiled and ready to use.",
        ),
        (
            "Stoneware Mixing Bowl",
            "28.50",
            "A glazed stoneware bowl that holds two litres and stands steady on the "
            "counter.",
        ),
        (
            "Cast Iron Skillet, 26 cm",
            "45.00",
            "A pre-seasoned skillet that goes from the hob to the oven.",
        ),
        (
            "Stainless Steel Saucepan",
            "52.00",
            "A three-litre saucepan with a heavy base and a lid that seals.",
        ),
        (
            "Linen Tea Towel Set",
            "18.00",
            "Three washed linen towels that dry fast and soften with use.",
        ),
        (
            "Ceramic Pour-Over Coffee Set",
            "39.00",
            "A dripper and a matching jug for brewing one or two cups by hand.",
        ),
        (
            "Olive Wood Spoon Trio",
            "21.00",
            "Three hand-finished spoons for stirring, serving and tasting.",
        ),
        (
            "Glass Storage Jars, Set of 4",
            "26.00",
            "Four jars with airtight bamboo lids for flour, rice and pulses.",
        ),
    ],
    "Garden": [
        (
            "Galvanised Watering Can, 5 L",
            "29.00",
            "A five-litre can with a long spout and a rose for seedlings.",
        ),
        (
            "Forged Hand Trowel",
            "16.50",
            "A trowel forged from one piece of steel with an ash handle.",
        ),
        (
            "Terracotta Planter, Medium",
            "19.00",
            "A frost-resistant planter with a drainage hole and a saucer.",
        ),
        (
            "Pruning Secateurs",
            "24.00",
            "Bypass secateurs that cut stems up to 20 mm and lock shut.",
        ),
        (
            "Raised Bed Kit, 120 x 60 cm",
            "89.00",
            "Pine boards and corner posts for a raised bed that builds in an hour.",
        ),
        (
            "Seed Starter Tray Set",
            "14.00",
            "Six trays with clear lids for sowing indoors in early spring.",
        ),
        (
            "Garden Kneeler with Handles",
            "33.00",
            "A padded kneeler that flips over to become a low seat.",
        ),
        (
            "Wildflower Seed Mix, 500 g",
            "12.00",
            "A blend of native meadow flowers that covers about twenty square metres.",
        ),
    ],
    "Stationery": [
        (
            "A5 Dot Grid Notebook",
            "11.00",
            "A hardback notebook with 192 numbered pages of dotted paper.",
        ),
        (
            "Brass Fountain Pen",
            "58.00",
            "A weighty pen with a medium nib and a screw-in converter.",
        ),
        (
            "Recycled Paper Desk Pad",
            "9.50",
            "Fifty tear-off sheets of recycled paper with a weekly planner grid.",
        ),
        (
            "Pencil Case in Waxed Canvas",
            "17.00",
            "A zipped canvas case that holds a dozen pencils and a ruler.",
        ),
        (
            "Ink Set, Six Colours",
            "27.00",
            "Six 30 ml bottles of water-based ink for fountain pens and dip pens.",
        ),
        (
            "Linen-Bound Sketchbook",
            "15.50",
            "A sewn sketchbook with heavy cartridge paper that takes pencil and wash.",
        ),
        (
            "Letter Writing Set",
            "22.00",
            "Twenty sheets, twenty envelopes and a sheet of address labels.",
        ),
        (
            "Desk Organiser in Oak",
            "36.00",
            "An oak tray with slots for pens, cards and a phone.",
        ),
    ],
    "Bags": [
        (
            "Waxed Canvas Backpack",
            "92.00",
            "A 20-litre backpack with a padded laptop sleeve and a roll top.",
        ),
        (
            "Leather Weekend Bag",
            "185.00",
            "A full-grain leather holdall that fits two days of clothes.",
        ),
        (
            "Cotton Tote Bag",
            "14.00",
            "A tote with a flat base and long handles that fits a week of shopping.",
        ),
        (
            "Crossbody Satchel",
            "74.00",
            "A compact satchel with an adjustable strap and two inner pockets.",
        ),
        (
            "Drawstring Gym Sack",
            "19.50",
            "A light sack in ripstop fabric with a zipped pocket for keys.",
        ),
        (
            "Zip Pouch Set of Three",
            "23.00",
            "Three pouches in nested sizes for cables, toiletries and receipts.",
        ),
        (
            "Insulated Lunch Bag",
            "27.00",
            "A roll-top bag with a foil lining that keeps food cool for six hours.",
        ),
        (
            "Canvas Duffel, 40 L",
            "68.00",
            "A hard-wearing duffel with a shoulder strap and a wet pocket.",
        ),
    ],
    "Lighting": [
        (
            "Brass Desk Lamp",
            "79.00",
            "An adjustable lamp with a weighted base and a warm LED bulb.",
        ),
        (
            "Paper Pendant Shade",
            "31.00",
            "A folded paper shade, 45 cm across, for a standard ceiling fitting.",
        ),
        (
            "Rechargeable Table Lantern",
            "48.00",
            "A cordless lantern that runs for twelve hours on one charge.",
        ),
        (
            "Beeswax Taper Candles, Box of 12",
            "20.00",
            "Twelve hand-dipped candles that burn for about seven hours each.",
        ),
        (
            "Glass Hurricane Candle Holder",
            "24.00",
            "A tall glass shade that keeps a pillar candle steady in a draught.",
        ),
        (
            "Clip-On Reading Light",
            "22.50",
            "A light with a flexible neck that clips to a bed frame or a book.",
        ),
        (
            "Warm White String Lights, 10 m",
            "26.00",
            "Ten metres of fine wire lights for a shelf, a mantel or a fence.",
        ),
        (
            "Ceramic Oil Lamp",
            "38.00",
            "A glazed lamp with a cotton wick for a soft flame indoors.",
        ),
    ],
}


def _entries(category: Category, position: int) -> list[tuple[str, str, str]]:
    """The products that fit ``category``: its own list, else one by position."""
    if category.name in CATALOG:
        return CATALOG[category.name]
    return list(CATALOG.values())[position % len(CATALOG)]


class CategorySeeder(karni.CategorySeeder):
    """Product groups, named for what they hold."""

    def seed(self, context: SeedContext) -> list[Any]:
        return [
            context.create(1, name=cycled(list(CATALOG), number))[0]
            for number in range(context.count)
        ]


class ProductSeeder(karni.ProductSeeder):
    """Products on sale, each in a category that fits it, most of them in stock."""

    active = True
    stock = FuzzyChoice([0, 5, 12, 40, 40])

    def seed(self, context: SeedContext) -> list[Any]:
        categories = list(Category.objects.order_by("name"))
        rows: list[Any] = []
        used: Counter[str] = Counter()
        for number in range(context.count):
            if not categories:
                rows += context.create(1)
                continue
            position = number % len(categories)
            category = categories[position]
            entries = _entries(category, position)
            round_ = number // len(categories)
            name, price, description = entries[round_ % len(entries)]
            used[name] += 1
            name = cycled([name], used[name] - 1)  # a name used before gets a number
            rows += context.create(
                1,
                category=category,
                name=name,
                price=Decimal(price),
                description=description,
            )
        return rows


class CartSeeder(karni.CartSeeder):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class CartItemSeeder(karni.CartItemSeeder):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    quantity = FuzzyChoice([1, 1, 2, 3])


class OrderSeeder(karni.OrderSeeder):
    """Orders start empty: their items make the total."""

    total = Decimal("0.00")


class OrderItemSeeder(karni.OrderItemSeeder):
    """Each item at its product's price."""

    quantity = FuzzyChoice([1, 1, 2, 3])
    unit_price = factory.LazyAttribute(lambda item: item.product.price)

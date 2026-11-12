"""market demo data for karni seed. Each seeder extends the one karni build writes in
market/karni/seeds.py: steer a field's values here.

The sellers and listings are invented. Replace SELLERS with your own.
"""

from collections import Counter
from decimal import Decimal
from typing import Any, NamedTuple

from karni.seeding import SeedContext, cycled
from market.karni import seeds as karni

from market.models import Listing, Seller


class Shopfront(NamedTuple):
    name: str
    about: str
    listings: tuple[
        tuple[str, str, str], ...
    ]  # a listing's title, price and description


SELLERS = [
    Shopfront(
        "Hollow Oak Pottery",
        "A two-person studio in a converted barn making everyday stoneware by hand.",
        (
            (
                "Speckled Stoneware Mug",
                "18.00",
                "A 300 ml mug with a speckled glaze and a thumb rest, thrown and "
                "fired by hand.",
            ),
            (
                "Set of Four Dinner Plates",
                "64.00",
                "Four 26 cm plates in a matte oat glaze that stack neatly and go in "
                "the dishwasher.",
            ),
            (
                "Large Serving Bowl",
                "42.00",
                "A wide bowl for salads and pasta, glazed inside with a pale blue "
                "wash.",
            ),
            (
                "Ceramic Utensil Crock",
                "26.00",
                "A tall crock that keeps spoons and spatulas by the hob.",
            ),
            (
                "Butter Dish with Lid",
                "24.50",
                "A lidded dish that keeps a block of butter soft and covered.",
            ),
            (
                "Hand-Painted Egg Cups, Pair",
                "16.00",
                "Two egg cups with a hand-painted rim in rust and cream.",
            ),
        ),
    ),
    Shopfront(
        "Tidewater Leatherworks",
        "Leather goods cut and stitched by one maker from vegetable-tanned hides.",
        (
            (
                "Slim Card Wallet",
                "34.00",
                "A wallet for six cards and folded notes that darkens as it ages.",
            ),
            (
                "Stitched Key Holder",
                "15.00",
                "A key holder for up to six keys, hand-stitched with waxed thread.",
            ),
            (
                "Leather Watch Strap, 20 mm",
                "28.00",
                "A strap in tan leather with a brass buckle, cut to fit a 20 mm lug.",
            ),
            (
                "Passport Cover",
                "30.00",
                "A cover with a slot for a boarding pass and a pen loop.",
            ),
            (
                "Dog Lead, 1.2 m",
                "38.00",
                "A round-stitched lead with a solid brass clip for medium dogs.",
            ),
            (
                "Notebook Sleeve, A5",
                "36.00",
                "A snug sleeve that holds an A5 notebook and a pencil.",
            ),
        ),
    ),
    Shopfront(
        "Marrow and Moss Candles",
        "Small-batch candles poured in reused glass from soy wax and plant-based "
        "scent.",
        (
            (
                "Cedar and Smoke Candle",
                "22.00",
                "A 220 g candle with a woody scent that burns for about forty hours.",
            ),
            (
                "Wild Mint Candle",
                "20.00",
                "A fresh green scent in a reused amber jar, 200 g.",
            ),
            (
                "Beeswax Pillar, 15 cm",
                "17.00",
                "A plain pillar candle in unbleached beeswax with a cotton wick.",
            ),
            (
                "Candle Making Kit",
                "39.00",
                "Wax, wicks, a jar and a scent oil for pouring your first two candles.",
            ),
            (
                "Fig and Amber Votive Set",
                "19.00",
                "Three votives that each burn for ten hours.",
            ),
            (
                "Wick Trimmer",
                "13.00",
                "A brass trimmer that cuts the wick to the right length for a clean "
                "flame.",
            ),
        ),
    ),
    Shopfront(
        "Brindle Lane Woodcraft",
        "Furniture and kitchenware turned and carved from fallen timber in a village "
        "workshop.",
        (
            (
                "Walnut Serving Board",
                "48.00",
                "A board with a leather loop for cheese and bread, finished in "
                "food-safe oil.",
            ),
            (
                "Turned Ash Salad Servers",
                "27.00",
                "A long-handled pair that rests on the edge of a bowl.",
            ),
            (
                "Oak Wall Shelf, 60 cm",
                "56.00",
                "A floating shelf with hidden brackets that takes books and plants.",
            ),
            (
                "Carved Spoon, Cherry",
                "21.00",
                "A spoon carved from one branch, sanded smooth and oiled.",
            ),
            (
                "Pepper Mill in Beech",
                "32.00",
                "A hand-turned mill with a ceramic grinder that adjusts from fine to "
                "coarse.",
            ),
            (
                "Bedside Stool",
                "95.00",
                "A small three-legged stool in oak, wide enough for a lamp and a book.",
            ),
        ),
    ),
    Shopfront(
        "Saltmarsh Textiles",
        "Woven and block-printed homewares made on small looms by a family workshop.",
        (
            (
                "Block-Printed Cushion Cover",
                "29.00",
                "A 45 cm linen cover with a printed leaf pattern and a hidden zip.",
            ),
            (
                "Wool Throw, Moss Green",
                "88.00",
                "A 140 by 180 cm throw woven from lambswool with a short fringe.",
            ),
            (
                "Linen Napkins, Set of Six",
                "36.00",
                "Six stonewashed napkins in natural flax with a mitred corner.",
            ),
            (
                "Woven Table Runner",
                "34.00",
                "A 150 cm runner with a plain weave and a striped edge.",
            ),
            (
                "Cotton Apron",
                "31.00",
                "A cross-back apron in thick canvas with a deep front pocket.",
            ),
            (
                "Hand-Dyed Tea Towel",
                "14.00",
                "A cotton towel dyed in indigo with a shibori fold.",
            ),
        ),
    ),
]


def _shopfront(seller: Seller, position: int) -> Shopfront:
    """The shopfront a seller row was made from (also suffixed), else by position."""
    for shopfront in SELLERS:
        if seller.name.startswith(shopfront.name):
            return shopfront
    return SELLERS[position % len(SELLERS)]


class SellerSeeder(karni.SellerSeeder):
    """Makers and shops, each with a line about what they make."""

    def seed(self, context: SeedContext) -> list[Any]:
        names = [shopfront.name for shopfront in SELLERS]
        return [
            context.create(
                1,
                name=cycled(names, number),
                about=SELLERS[number % len(SELLERS)].about,
            )[0]
            for number in range(context.count)
        ]


class ListingSeeder(karni.ListingSeeder):
    """Things each seller makes, at a price and with a description that fit them."""

    def seed(self, context: SeedContext) -> list[Any]:
        sellers = list(Seller.objects.order_by("name"))
        rows: list[Any] = []
        used: Counter[str] = Counter()
        for number in range(context.count):
            if not sellers:
                rows += context.create(1)
                continue
            position = number % len(sellers)
            seller = sellers[position]
            items = _shopfront(seller, position).listings
            turn = number // len(sellers)
            title, price, description = items[turn % len(items)]
            used[title] += 1
            title = cycled(
                [title], used[title] - 1
            )  # a title used before gets a number
            rows += context.create(
                1,
                seller=seller,
                title=title,
                price=Decimal(price),
                description=description,
                active=number % 8 != 7,  # one in eight is paused
            )
        return rows


class OrderSeeder(karni.OrderSeeder):
    """Orders for listings on sale: one to three of each, at the listing's price."""

    def seed(self, context: SeedContext) -> list[Any]:
        listings = list(Listing.objects.filter(active=True).order_by("title", "pk"))
        rows: list[Any] = []
        for number in range(context.count):
            if not listings:
                rows += context.create(1)
                continue
            listing = listings[number * 7 % len(listings)]
            quantity = (1, 1, 2, 1, 3)[number % 5]
            rows += context.create(
                1, listing=listing, quantity=quantity, amount=listing.price * quantity
            )
        return rows


class PayoutSeeder(karni.PayoutSeeder):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

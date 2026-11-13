"""shop demo data for karni seed. Each seeder extends the one karni build writes in
shop/karni/seeds.py: steer a field's values here.

The categories, products, prices, people and addresses are invented. Replace CATALOG
with your own, or load real rows with an import. Every picture is drawn
(karni.seeding.placeholder_image): the same seed gives the same shop.

Some products come in sizes or colours (VARIABLE): each way is a variation with its
own SKU and stock. The shop sends by zones (Europe, the United Kingdom, the United
States, the rest of the world) with a flat rate, free shipping above an amount and
local pickup, charges tax by country, and has coupons of each kind (SHOP_SETUP).

Orders are placed through karni-commerce, as a shopper's would be: each holds its
stock, a paid one takes it and gets its parcel, and the demo shows every money state
(waiting, paid, failed, cancelled, refunded) and every parcel state (processing,
shipped, delivered). Some use a coupon. Payments are the test provider's, made on the
spot, and no email goes out while the demo is made (karni.mail.silenced). The buyers
whose parcels arrived review what they bought, and the customer keeps a wishlist.

Demo logins (password karni-password): demo@example.com (admin, every permission),
manager@example.com (the whole shop, refunds included), staff@example.com (orders,
parcels and the catalogue) and customer@example.com (a customer with orders in every
state).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone
from karni.accounts.permissions import assign_role
from karni.mail import silenced
from karni.seeding import SeedContext, Seeder, cycled, placeholder_image
from karni_commerce import services as commerce
from karni_commerce.models import (
    Coupon,
    CouponUse,
    Order,
    OrderLine,
    OrderPayment,
    OrderRefund,
    ShippingMethod,
    ShippingZone,
    TaxRate,
)
from karni_payments.models import Payment, Refund
from rest_framework.exceptions import ValidationError

from shop.karni import seeds as karni
from shop.models import (
    Attribute,
    AttributeValue,
    Category,
    Product,
    Review,
    Shipment,
    Tag,
    Variation,
    WishlistItem,
)

CATALOG: dict[str, dict[str, list[tuple[str, str, str]]]] = {
    "Kitchen": {
        "Cookware": [
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
                "Stoneware Mixing Bowl",
                "28.50",
                (
                    "A glazed stoneware bowl that holds two litres and stands steady "
                    "on the counter."
                ),
            ),
            (
                "Beech Wood Chopping Board",
                "34.00",
                "A thick beech board with a juice groove, oiled and ready to use.",
            ),
        ],
        "Table and Storage": [
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
    },
    "Garden": {
        "Tools": [
            (
                "Forged Hand Trowel",
                "16.50",
                "A trowel forged from one piece of steel with an ash handle.",
            ),
            (
                "Pruning Secateurs",
                "24.00",
                "Bypass secateurs that cut stems up to 20 mm and lock shut.",
            ),
            (
                "Garden Kneeler with Handles",
                "33.00",
                "A padded kneeler that flips over to become a low seat.",
            ),
            (
                "Galvanised Watering Can, 5 L",
                "29.00",
                "A five-litre can with a long spout and a rose for seedlings.",
            ),
        ],
        "Growing": [
            (
                "Terracotta Planter, Medium",
                "19.00",
                "A frost-resistant planter with a drainage hole and a saucer.",
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
                "Wildflower Seed Mix, 500 g",
                "12.00",
                (
                    "A blend of native meadow flowers that covers about twenty square "
                    "metres."
                ),
            ),
        ],
    },
    "Stationery": {
        "Writing": [
            (
                "Brass Fountain Pen",
                "58.00",
                "A weighty pen with a medium nib and a screw-in converter.",
            ),
            (
                "Ink Set, Six Colours",
                "27.00",
                "Six 30 ml bottles of water-based ink for fountain pens and dip pens.",
            ),
            (
                "Letter Writing Set",
                "22.00",
                "Twenty sheets, twenty envelopes and a sheet of address labels.",
            ),
            (
                "Recycled Paper Desk Pad",
                "9.50",
                "Fifty tear-off sheets of recycled paper with a weekly planner grid.",
            ),
        ],
        "Paper and Desk": [
            (
                "A5 Dot Grid Notebook",
                "11.00",
                "A hardback notebook with 192 numbered pages of dotted paper.",
            ),
            (
                "Linen-Bound Sketchbook",
                "15.50",
                (
                    "A sewn sketchbook with heavy cartridge paper that takes pencil "
                    "and wash."
                ),
            ),
            (
                "Pencil Case in Waxed Canvas",
                "17.00",
                "A zipped canvas case that holds a dozen pencils and a ruler.",
            ),
            (
                "Desk Organiser in Oak",
                "36.00",
                "An oak tray with slots for pens, cards and a phone.",
            ),
        ],
    },
    "Bags": {
        "Travel": [
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
                "Canvas Duffel, 40 L",
                "68.00",
                "A hard-wearing duffel with a shoulder strap and a wet pocket.",
            ),
            (
                "Drawstring Gym Sack",
                "19.50",
                "A light sack in ripstop fabric with a zipped pocket for keys.",
            ),
        ],
        "Everyday": [
            (
                "Cotton Tote Bag",
                "14.00",
                (
                    "A tote with a flat base and long handles that fits a week of "
                    "shopping."
                ),
            ),
            (
                "Crossbody Satchel",
                "74.00",
                "A compact satchel with an adjustable strap and two inner pockets.",
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
        ],
    },
    "Lighting": {
        "Lamps": [
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
                "Clip-On Reading Light",
                "22.50",
                "A light with a flexible neck that clips to a bed frame or a book.",
            ),
        ],
        "Candles and Lights": [
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
    },
}

TAGS = [
    "Gift idea",
    "Handmade",
    "Bestseller",
    "Eco",
    "New",
    "Limited",
    "Local",
    "Classic",
]

#: The options products come in, with their values in order.
ATTRIBUTES: dict[str, list[str]] = {
    "Size": ["S", "M", "L", "XL"],
    "Colour": ["Natural", "Charcoal", "Sage"],
}

#: The products sold in several ways: name -> (attribute, [(value, price or None)]).
VARIABLE: dict[str, tuple[str, list[tuple[str, str | None]]]] = {
    "Linen Tea Towel Set": (
        "Colour",
        [("Natural", None), ("Charcoal", None), ("Sage", None)],
    ),
    "Cotton Tote Bag": (
        "Colour",
        [("Natural", None), ("Charcoal", None), ("Sage", None)],
    ),
    "Canvas Duffel, 40 L": ("Colour", [("Natural", None), ("Charcoal", "72.00")]),
    "Insulated Lunch Bag": (
        "Size",
        [("S", "22.00"), ("M", None), ("L", "32.00")],
    ),
    "Crossbody Satchel": ("Colour", [("Charcoal", None), ("Sage", None)]),
    "A5 Dot Grid Notebook": (
        "Colour",
        [("Natural", None), ("Charcoal", None), ("Sage", None)],
    ),
    "Drawstring Gym Sack": ("Size", [("M", None), ("L", "21.50")]),
}

#: Where the shop sends and for how much: zone -> (countries, [(method, kind, cost,
#: free above)]). The last zone, with no countries, is everywhere else.
ZONES: list[tuple[str, str, list[tuple[str, str, str, str | None]]]] = [
    (
        "United States",
        "US",
        [
            ("Standard", "flat", "5.00", "50.00"),
            ("Local pickup", "pickup", "0.00", None),
        ],
    ),
    (
        "Europe",
        "AT, BE, DE, DK, ES, FI, FR, IE, IT, NL, PT, SE",
        [("Standard", "flat", "6.50", "75.00"), ("Express", "flat", "14.00", None)],
    ),
    ("United Kingdom", "GB", [("Standard", "flat", "9.00", None)]),
    ("Rest of the world", "", [("International", "flat", "19.00", None)]),
]

#: The demo's tax: (name, country, rate). Blank country: everywhere else.
TAXES = [("Sales tax", "US", "7"), ("VAT", "", "20")]

#: The demo's coupons: (code, description, kind, amount, minimum spend, per person).
COUPONS: list[tuple[str, str, str, str, str | None, int | None]] = [
    ("WELCOME10", "10% off a first order", "percent", "10", None, 1),
    ("SAVE5", "5 off orders of 40 or more", "fixed", "5", "40.00", None),
    ("FREESHIP", "Free shipping over 30", "free_shipping", "0", "30.00", None),
    ("KITCHEN15", "15% off the kitchen", "percent", "15", None, None),
    ("SUMMER20", "20% off, ended last month", "percent", "20", None, None),
]

#: The people of the demo: (email, first name, last name, city, postcode, country,
#: role).
PEOPLE = [
    ("customer@example.com", "Mira", "Okafor", "Lisbon", "1100-148", "PT", "customer"),
    ("staff@example.com", "Theo", "Lindqvist", "Malmo", "211 22", "SE", "shop-staff"),
    ("manager@example.com", "Iris", "Bauer", "Bremen", "28195", "DE", "shop-manager"),
    ("ana.rios@example.com", "Ana", "Rios", "Valencia", "46001", "ES", "customer"),
    ("jon.mbeki@example.com", "Jon", "Mbeki", "Leeds", "LS1 4AP", "GB", "customer"),
    ("lena.vogt@example.com", "Lena", "Vogt", "Graz", "8010", "AT", "customer"),
    ("sam.ito@example.com", "Sam", "Ito", "Osaka", "530-0001", "JP", "customer"),
]

#: What happens to each demo order, in turn: its money and its parcel.
STORIES = [
    "delivered",
    "shipped",
    "processing",
    "pending",
    "delivered",
    "failed",
    "cancelled",
    "refunded",
    "part_refunded",
    "shipped",
    "delivered",
    "delivered",
]

#: Where a seeded payment says it came from (karni seed --reset removes these).
SEED_SESSION = "seed_cs_"


def anchor(context: SeedContext) -> datetime:
    """The moment the seed's dates count from (today, or the seed's ``now``)."""
    found = getattr(context.run, "anchor", None)
    return found if isinstance(found, datetime) else timezone.now()


def people(context: SeedContext) -> list[Any]:
    """The demo's people, one login per role of karni.yaml (karni seed lists them)."""
    found = [
        context.account(email, role, first_name=first, last_name=last)
        for email, first, last, *_rest, role in PEOPLE
    ]
    demo = get_user_model().objects.filter(email="demo@example.com").first()
    if demo is not None:
        assign_role(demo, "admin")
    return found


def customers(context: SeedContext) -> list[Any]:
    return [
        user
        for user, entry in zip(people(context), PEOPLE, strict=True)
        if entry[6] == "customer"
    ]


def address_of(user: Any) -> dict[str, str]:
    entry = next(item for item in PEOPLE if item[0] == user.email)
    _email, first, last, city, postcode, country, _role = entry
    return {
        "name": f"{first} {last}",
        "company": "",
        "line1": f"{len(first) * 7} {last} Street",
        "line2": "",
        "city": city,
        "region": "",
        "postcode": postcode,
        "country": country,
        "phone": "",
    }


class CategorySeeder(karni.CategorySeeder):
    """Five top categories, each with its child categories and a drawn picture."""

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        tops = list(CATALOG)
        for number in range(min(context.count, len(tops))):
            name = tops[number]
            rows += context.create(
                1, name=name, parent=None, image=placeholder_image(name, key=name)
            )
        for top in list(rows):
            for child in CATALOG[top.name]:
                if len(rows) >= context.count:
                    return rows
                rows += context.create(
                    1,
                    name=child,
                    parent=top,
                    image=placeholder_image(child, key=top.name),
                )
        return rows


class TagSeeder(karni.TagSeeder):
    def seed(self, context: SeedContext) -> list[Any]:
        return [
            context.create(1, name=cycled(TAGS, n))[0] for n in range(context.count)
        ]


def _catalogue() -> list[tuple[Category, Category, tuple[str, str, str]]]:
    """``(top, child, product)`` for every product of CATALOG whose categories exist."""
    found = []
    for top in Category.objects.filter(parent__isnull=True).order_by("name"):
        for child_name, products in CATALOG.get(top.name, {}).items():
            child = Category.objects.filter(parent=top, name=child_name).first()
            if child is not None:
                found += [(top, child, product) for product in products]
    return found


class ProductSeeder(karni.ProductSeeder):
    """Products in their categories: some on sale, some low or out of stock, a few
    featured, one not for sale."""

    def seed(self, context: SeedContext) -> list[Any]:
        catalogue = _catalogue()
        tags = list(Tag.objects.order_by("name"))
        now = anchor(context)
        rows: list[Any] = []
        for number in range(context.count):
            if not catalogue:
                rows += context.create(1)
                continue
            top, child, (name, price, short) = catalogue[number % len(catalogue)]
            name = cycled([name], number // len(catalogue))
            regular = Decimal(price)
            values: dict[str, Any] = {
                "name": name,
                "sku": f"{top.name[:3].upper()}-{number + 1:03d}",
                "short_description": short,
                "description": f"{short}\n\nMade to last, sent in recycled packaging.",
                "price": regular,
                "sale_price": None,
                "sale_starts": None,
                "sale_ends": None,
                "stock": [24, 12, 40, 3, 0, 18, 7, 30][number % 8],
                # a few keep their own low-stock level, and two take backorders
                "low_stock": 8 if number % 7 == 6 else None,
                "backorders": number in (12, 28),
                "active": number % 13 != 12,
                "featured": number % 5 == 0,
                "image": placeholder_image(name, key=top.name),
                # the reviews count them (ReviewSeeder)
                "rating_average": None,
                "rating_count": 0,
            }
            if number % 6 == 1:  # on sale now, until next week
                values["sale_price"] = (regular * Decimal("0.8")).quantize(
                    Decimal("0.01")
                )
                values["sale_starts"] = now - timedelta(days=3)
                values["sale_ends"] = now + timedelta(days=7)
            elif number % 6 == 4:  # a sale that starts next week
                values["sale_price"] = (regular * Decimal("0.9")).quantize(
                    Decimal("0.01")
                )
                values["sale_starts"] = now + timedelta(days=7)
            [product] = context.create(1, **values)
            product.categories.set([child])
            if tags:
                product.tags.set(
                    [tags[number % len(tags)], tags[(number * 3 + 1) % len(tags)]]
                )
            rows.append(product)
        return rows


class ProductImageSeeder(karni.ProductImageSeeder):
    """More pictures of the first products: a second and a third view."""

    def seed(self, context: SeedContext) -> list[Any]:
        products = list(Product.objects.order_by("sku"))
        rows: list[Any] = []
        for number in range(context.count):
            if not products:
                break
            product = products[(number // 2) % len(products)]
            view = number % 2 + 2
            top = product.categories.first()
            key = top.parent.name if top is not None and top.parent else product.name
            rows += context.create(
                1,
                product=product,
                position=view,
                alt=f"{product.name}, view {view}",
                image=placeholder_image(f"{product.name} {view}", key=key),
            )
        return rows


class AttributeSeeder(karni.AttributeSeeder):
    """The options: Size and Colour."""

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        for position, name in enumerate(list(ATTRIBUTES)[: context.count]):
            rows += context.create(1, name=name, position=position)
        return rows


class AttributeValueSeeder(karni.AttributeValueSeeder):
    """Each option's values, in their order."""

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        for attribute in Attribute.objects.order_by("position"):
            for position, value in enumerate(ATTRIBUTES.get(attribute.name, [])):
                if len(rows) >= context.count:
                    return rows
                rows += context.create(
                    1, attribute=attribute, value=value, position=position
                )
        return rows


class VariationSeeder(karni.VariationSeeder):
    """The ways the VARIABLE products are sold: own SKUs and stock, some sold out."""

    class Meta(karni.VariationSeeder.Meta):
        after = ("shop.Product", "shop.AttributeValue")

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        stocks = [12, 6, 0, 20, 2, 9]
        for name, (attribute, ways) in VARIABLE.items():
            product = Product.objects.filter(name=name).order_by("sku").first()
            if product is None:
                continue
            for position, (value, price) in enumerate(ways):
                if len(rows) >= context.count:
                    return rows
                found = AttributeValue.objects.filter(
                    attribute__name=attribute, value=value
                ).first()
                stock = stocks[len(rows) % len(stocks)]
                [row] = context.create(
                    1,
                    product=product,
                    sku=f"{product.sku}-{value[:3].upper()}",
                    price=Decimal(price) if price else None,
                    sale_price=None,
                    stock=stock,
                    available=stock,
                    image=placeholder_image(f"{name} {value}", key=value),
                    active=True,
                    position=position,
                )
                if found is not None:
                    row.values.set([found])
                rows.append(row)
            # The product's own stock is its variations' (staff read one figure).
            total = sum(row.stock for row in rows if row.product_id == product.pk)
            Product.objects.filter(pk=product.pk).update(stock=total, available=total)
        return rows


def shop_setup(now: datetime) -> list[Coupon]:
    """The demo's shipping zones and methods, tax rates and coupons (made again)."""
    CouponUse.objects.without("soft_delete", reason="a new demo").all().hard_delete()
    for model in (Coupon, ShippingMethod, ShippingZone, TaxRate):
        model.objects.without("soft_delete", reason="a new demo").all().hard_delete()
    for position, (zone_name, countries, methods) in enumerate(ZONES):
        zone = ShippingZone.objects.create(
            name=zone_name, countries=countries, position=position
        )
        for order, (name, kind, cost, free_above) in enumerate(methods):
            ShippingMethod.objects.create(
                zone=zone,
                name=name,
                kind=kind,
                cost=Decimal(cost),
                free_above=Decimal(free_above) if free_above else None,
                position=order,
            )
    for name, country, rate in TAXES:
        TaxRate.objects.create(name=name, country=country, rate=Decimal(rate))
    kitchen = Category.objects.filter(name="Kitchen", parent__isnull=True).first()
    coupons = []
    for code, description, kind, amount, minimum, per_person in COUPONS:
        ended = code == "SUMMER20"
        coupons.append(
            Coupon.objects.create(
                code=code,
                description=description,
                kind=kind,
                amount=Decimal(amount),
                minimum_spend=Decimal(minimum) if minimum else None,
                usage_limit_per_person=per_person,
                starts_at=now - timedelta(days=60) if ended else None,
                ends_at=now - timedelta(days=30) if ended else None,
                limits=(
                    {"categories": [{"key": str(kitchen.pk), "name": kitchen.name}]}
                    if code == "KITCHEN15" and kitchen is not None
                    else {}
                ),
            )
        )
    return coupons


class OrderSeeder(Seeder):
    """Orders come with the parcels (ShipmentSeeder runs after the products exist)."""

    class Meta:
        model = Order
        count = 0


def _forget_the_last_demo() -> None:
    """karni seed --reset: the orders, payments and refunds of the last demo go."""
    for model in (CouponUse, OrderRefund, OrderPayment, OrderLine, Order):
        model.objects.without("soft_delete", reason="a new demo").all().hard_delete()
    seeded = Payment.objects.filter(checkout_session_id__startswith=SEED_SESSION)
    Refund.objects.filter(payment__in=seeded).hard_delete()
    seeded.hard_delete()


def _pay(order: Order, ok: bool = True) -> Payment:
    """The order's payment, as the provider would report it."""
    payment = Payment.objects.create(
        id=uuid.UUID(int=order.number),
        user=order.user,
        amount=order.balance,
        currency=order.currency.lower(),
        provider="test",
        status=Payment.Status.SUCCEEDED if ok else Payment.Status.FAILED,
        checkout_session_id=f"{SEED_SESSION}{order.number}",
        metadata={"commerce_order": str(order.pk), "number": order.number},
    )
    OrderPayment.objects.create(
        order=order, payment=payment, currency=order.currency, amount=order.balance
    )
    commerce.settle(payment)
    order.refresh_from_db()
    return payment


def _refund(order: Order, payment: Payment, *, full: bool) -> None:
    """A refund the provider confirmed: all of it, or the first line back in stock."""
    first = order.lines.order_by("position").first()
    amount = (
        order.amount_paid
        if full or first is None
        else first.unit_paid().quantize(Decimal("0.01"))
    )
    refund = Refund.objects.create(
        payment=payment,
        amount=amount,
        status=Refund.Status.SUCCEEDED,
        reason="damaged in transit" if not full else "changed their mind",
    )
    lines: dict[str, int] = {} if full or first is None else {str(first.pk): 1}
    OrderRefund.objects.create(
        order=order,
        refund=refund,
        currency=order.currency,
        amount=amount,
        lines=lines,
        restock=not full,
        reason=refund.reason,
    )
    commerce.settle_refund(refund)
    Payment.objects.filter(pk=payment.pk).update(
        status=Payment.Status.REFUNDED if full else Payment.Status.PARTIALLY_REFUNDED
    )


class ShipmentSeeder(karni.ShipmentSeeder):
    """The demo's orders, placed through karni-commerce, and their parcels.

    ``seed: {Shipment: n}`` in karni.yaml is how many orders to place. Each paid one
    gets its parcel, which then moves to shipped or delivered as its story says.
    """

    class Meta(karni.ShipmentSeeder.Meta):
        after = ("shop.Product",)  # the orders buy the products, seeded first

    def seed(self, context: SeedContext) -> list[Any]:
        _forget_the_last_demo()
        shop_setup(anchor(context))
        buyers = customers(context)
        products = list(
            Product.objects.filter(active=True, stock__gt=0).order_by("sku")
        )
        if not products or not buyers:
            return []
        now = anchor(context)
        with silenced():
            for number in range(context.count):
                self.story(context, number, buyers, products, now)
        return list(Shipment.objects.order_by("created_at"))

    def story(
        self,
        context: SeedContext,
        number: int,
        buyers: list[Any],
        products: list[Product],
        now: datetime,
    ) -> None:
        story = STORIES[number % len(STORIES)]
        guest = number % 9 == 8
        buyer = buyers[number % len(buyers)]
        lines: list[tuple[str, str, int, dict[str, Any]]] = []
        for k in range(1 + number % 3):
            product = products[(number * 3 + k) % len(products)]
            ways = list(
                Variation.objects.filter(
                    product=product, active=True, available__gt=0
                ).order_by("position")
            )
            options = {"variation": str(ways[number % len(ways)].pk)} if ways else {}
            lines.append(("product", str(product.pk), k + 1, options))
        # A few demo orders used a coupon: the welcome one, and free shipping.
        coupon = {1: "WELCOME10", 9: "FREESHIP", 13: "SAVE5"}.get(number)
        try:
            order = commerce.place_order(
                lines,
                user=None if guest else buyer,
                email=f"guest{number}@example.com" if guest else buyer.email,
                name=address_of(buyer)["name"],
                billing=address_of(buyer),
                shipping=address_of(buyer),
                note="Please leave it with the neighbour." if number % 5 == 0 else "",
                coupon=coupon,
            )
        except ValidationError:
            try:  # the coupon does not fit this order: placed without it
                order = commerce.place_order(
                    lines,
                    user=None if guest else buyer,
                    email=f"guest{number}@example.com" if guest else buyer.email,
                    name=address_of(buyer)["name"],
                    billing=address_of(buyer),
                    shipping=address_of(buyer),
                )
            except ValidationError:
                return  # sold out since: this story is skipped
        placed = now - timedelta(days=(context.count - number) // 2, hours=number % 7)
        this = Order.objects.filter(pk=order.pk)
        if story == "pending":
            # a demo order waiting for its payment keeps its stock for two days
            held = {"hold_until": now + timedelta(days=2)}
            this.update(**held)  # karni: allow(audited-bulk-write): demo data
            placed = now - timedelta(minutes=5)
        elif story == "cancelled":
            commerce.cancel(order, "the customer changed their mind")
        else:
            payment = _pay(order, ok=story != "failed")
            if story in ("refunded", "part_refunded"):
                _refund(order, payment, full=story == "refunded")
        shipment = Shipment.objects.filter(order=order).first()
        if shipment is not None and story in ("shipped", "delivered", "part_refunded"):
            shipment.transition(
                "status",
                "shipped",
                carrier="Parcel Post",
                tracking_number=f"PP{order.number}{number:03d}",
            )
            if story == "delivered":
                shipment.transition("status", "delivered")
        elif shipment is not None and story == "refunded":
            shipment.transition("status", "cancelled")  # refunded before it was sent
        when: dict[str, Any] = {"created_at": placed}
        if Order.objects.filter(pk=order.pk, paid_at__isnull=False).exists():
            when["paid_at"] = placed + timedelta(minutes=10)  # paid as it was placed
        this.update(**when)  # karni: allow(audited-bulk-write): demo data
        parcels = Shipment.objects.filter(order=order)
        later = {"created_at": placed + timedelta(hours=1)}
        parcels.update(**later)  # karni: allow(audited-bulk-write): demo data


#: The words of the demo's reviews, by rating.
REVIEW_WORDS = {
    5: (
        "Just what I wanted",
        "Well made and it arrived quickly. I would buy it again.",
    ),
    4: ("Very good", "Good quality for the price. The colour is a little darker."),
    3: ("Fine", "It does the job, though the finish could be better."),
    2: ("Not for me", "Smaller than I expected from the pictures."),
}


class ReviewSeeder(karni.ReviewSeeder):
    """Reviews by the buyers whose parcels arrived: most approved, one waiting, one
    rejected. Each product's rating counts the approved ones. The demo customer's
    parcels are left unreviewed, so customer@example.com has something to review."""

    class Meta(karni.ReviewSeeder.Meta):
        after = ("shop.Shipment",)

    def pairs(self) -> list[tuple[Any, str]]:
        """Each (buyer, product) whose parcel arrived, but for the demo customer's."""
        delivered = (
            Shipment.objects.filter(status="delivered", order__user__isnull=False)
            .exclude(order__user__email="customer@example.com")
            .select_related("order__user")
            .order_by("created_at")
        )
        found: list[tuple[Any, str]] = []
        for shipment in delivered:
            for line in shipment.order.lines.filter(kind="product").order_by(
                "position"
            ):
                pair = (shipment.order.user, line.item)
                if pair not in found:
                    found.append(pair)
        return found

    def seed(self, context: SeedContext) -> list[Any]:
        Review.objects.without("soft_delete", reason="a new demo").all().hard_delete()
        pairs = self.pairs()
        # Only a buyer whose parcel arrived reviews: when too few did for the count,
        # more of the parcels on their way arrive, keeping one on its way.
        moving = list(
            Shipment.objects.filter(status="shipped", order__user__isnull=False)
            .exclude(order__user__email="customer@example.com")
            .order_by("created_at")
        )
        with silenced():
            while len(pairs) < context.count and len(moving) > 1:
                moving.pop(0).transition("status", "delivered")
                pairs = self.pairs()
        rows: list[Any] = []
        ratings = [5, 4, 5, 3, 4, 5, 2, 4]
        for number, (author, item) in enumerate(pairs[: context.count]):
            product = Product.objects.filter(pk=item).first()
            if product is None:
                continue
            rating = ratings[number % len(ratings)]
            title, body = REVIEW_WORDS[rating]
            status = (
                "pending" if number == 1 else "rejected" if number == 6 else "approved"
            )
            [review] = context.create(
                1,
                product=product,
                author=author,
                rating=rating,
                title=title,
                body=body,
                status="pending",
                verified=True,
            )
            if status != "pending":
                review.transition("status", status)
            rows.append(review)
        return rows


class WishlistItemSeeder(karni.WishlistItemSeeder):
    """What the demo customer keeps for later."""

    def seed(self, context: SeedContext) -> list[Any]:
        WishlistItem.objects.without(
            "soft_delete", reason="a new demo"
        ).all().hard_delete()
        customer = get_user_model().objects.filter(email="customer@example.com").first()
        if customer is None:
            return []
        products = list(
            Product.objects.filter(active=True, featured=True).order_by("sku")
        )
        rows: list[Any] = []
        for product in products[: context.count]:
            rows += context.create(1, user=customer, product=product)
        return rows

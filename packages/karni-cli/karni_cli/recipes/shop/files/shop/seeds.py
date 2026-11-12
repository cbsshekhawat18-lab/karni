"""shop demo data for karni seed. Each seeder extends the one karni build writes in
shop/karni/seeds.py: steer a field's values here.

The categories, products, prices, people and addresses are invented. Replace CATALOG
with your own, or load real rows with an import. Every picture is drawn
(karni.seeding.placeholder_image): the same seed gives the same shop.

Demo logins (password karni-password): demo@example.com (every permission),
staff@example.com (orders and the catalogue) and customer@example.com (a customer with
orders in every state).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone
from karni.accounts.permissions import assign_role
from karni.lifecycle import any_initial_state
from karni.seeding import SeedContext, cycled, placeholder_image
from karni.testing.factories import DEFAULT_PASSWORD
from karni_payments.models import Payment, Refund
from rest_framework.exceptions import ValidationError
from shop.karni import seeds as karni

from shop import services
from shop.models import Category, Order, OrderItem, Product, Tag, new_key

# top category -> its child categories -> (product name, price, short description).
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
                "A glazed stoneware bowl that holds two litres and stands steady on the counter.",
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
                "A blend of native meadow flowers that covers about twenty square metres.",
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
                "A sewn sketchbook with heavy cartridge paper that takes pencil and wash.",
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
                "A tote with a flat base and long handles that fits a week of shopping.",
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

#: The people of the demo: (email, first name, last name, city, postcode, country, role).
PEOPLE = [
    ("customer@example.com", "Mira", "Okafor", "Lisbon", "1100-148", "PT", "customer"),
    ("staff@example.com", "Theo", "Lindqvist", "Malmo", "211 22", "SE", "staff"),
    ("ana.rios@example.com", "Ana", "Rios", "Valencia", "46001", "ES", "customer"),
    ("jon.mbeki@example.com", "Jon", "Mbeki", "Leeds", "LS1 4AP", "GB", "customer"),
    ("lena.vogt@example.com", "Lena", "Vogt", "Graz", "8010", "AT", "customer"),
    ("sam.ito@example.com", "Sam", "Ito", "Osaka", "530-0001", "JP", "customer"),
]

#: Order states the demo shows, in order: every state a customer or staff can meet.
STATES = [
    "delivered",
    "shipped",
    "processing",
    "paid",
    "pending",
    "failed",
    "cancelled",
    "refunded",
]


def anchor(context: SeedContext) -> datetime:
    """The moment the seed's dates count from (the start of today, or the seed's ``now``)."""
    found = getattr(context.run, "anchor", None)
    return found if isinstance(found, datetime) else timezone.now()


def people() -> list[Any]:
    """The demo's people, each with their role (made once, found again on the next run)."""
    model = get_user_model()
    found = []
    for email, first, last, *_rest, role in PEOPLE:
        user = model.objects.filter(email=email).first()
        if user is None:
            user = model.objects.create_user(
                email=email, password=DEFAULT_PASSWORD, first_name=first, last_name=last
            )
            if hasattr(user, "email_verified"):
                user.email_verified = True
                user.save(update_fields=["email_verified"])
        assign_role(user, role)
        found.append(user)
    demo = model.objects.filter(email="demo@example.com").first()
    if demo is not None:
        assign_role(demo, "manager")
    return found


def customers() -> list[Any]:
    return [
        user
        for user, entry in zip(people(), PEOPLE, strict=True)
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
    """Five top categories, each with its child categories, each with a drawn picture."""

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
    """Products in their categories: some on sale, some low or out of stock, a few featured."""

    def seed(self, context: SeedContext) -> list[Any]:
        catalogue = _catalogue()
        tags = list(Tag.objects.order_by("name"))
        now = anchor(context)
        rows: list[Any] = []
        for number in range(context.count):
            if not catalogue:
                rows += context.create(1, reserved=0)
                continue
            top, child, (name, price, short) = catalogue[number % len(catalogue)]
            name = cycled([name], number // len(catalogue))
            regular = Decimal(price)
            values: dict[str, Any] = {
                "name": name,
                "sku": f"{top.name[:3].upper()}-{number + 1:03d}",
                "short_description": short,
                "description": f"{short}\n\nMade to last, and sent in recycled packaging.",
                "price": regular,
                "sale_price": None,
                "sale_starts": None,
                "sale_ends": None,
                "stock": [24, 12, 40, 3, 0, 18, 7, 30][number % 8],
                "reserved": 0,
                "active": number % 13 != 12,
                "featured": number % 5 == 0,
                "image": placeholder_image(name, key=top.name),
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


class AddressSeeder(karni.AddressSeeder):
    """Each customer's home address, and a second one for some (work, a friend's)."""

    def seed(self, context: SeedContext) -> list[Any]:
        found = customers()
        rows: list[Any] = []
        for number in range(context.count):
            user = found[number % len(found)]
            home = address_of(user)
            first = number < len(found)
            if not first:
                home["line1"] = f"{number * 11} Market Lane"
                home["company"] = "Studio North"
            rows += context.create(1, customer=user, is_default=first, **home)
        return rows


class OrderSeeder(karni.OrderSeeder):
    """Orders in every state, by customers and guests, over the last weeks.

    Their lines, totals and payments come with OrderItemSeeder, which runs once the
    products exist.
    """

    def seed(self, context: SeedContext) -> list[Any]:
        found = customers()
        rows: list[Any] = []
        now = anchor(context)
        # The payments of a seed before this one (karni seed --reset wipes the orders
        # only).
        Refund.objects.filter(
            payment__checkout_session_id__startswith="seed_cs_"
        ).hard_delete()
        Payment.objects.filter(checkout_session_id__startswith="seed_cs_").hard_delete()
        for number in range(context.count):
            state = STATES[number % len(STATES)]
            guest = number % 9 == 8
            customer = None if guest else found[number % len(found)]
            email = f"guest{number}@example.com" if guest else customer.email
            address = address_of(found[number % len(found)])
            placed = now - timedelta(
                days=(context.count - number) // 2, hours=number % 7
            )
            if state == "pending":
                placed = now - timedelta(minutes=5)
            with any_initial_state("demo orders start in every state"):
                [order] = context.create(
                    1,
                    number=1001 + number,
                    customer=customer,
                    email=email,
                    status=state,
                    subtotal=Decimal("0.00"),
                    total=Decimal("0.00"),
                    billing=address,
                    shipping=address,
                    note="Please leave it with the neighbour."
                    if number % 5 == 0
                    else "",
                    payment=None,
                    paid_at=None if state in ("pending", "failed") else placed,
                    # a demo order waiting for its payment keeps its stock for two days
                    reserved_until=now + timedelta(days=2)
                    if state == "pending"
                    else None,
                    key=new_key(),
                )
            this = Order.objects.filter(pk=order.pk)
            when = {"created_at": placed}
            this.update(**when)  # karni: allow(audited-bulk-write): demo data
            rows.append(order)
        return rows


class OrderItemSeeder(karni.OrderItemSeeder):
    """One to three lines per order at their product's price, then each order's totals,
    its
    payment and, for a cancelled or refunded order, its refund. A pending order holds
    its stock.
    """

    def seed(self, context: SeedContext) -> list[Any]:
        orders = list(Order.objects.order_by("number"))
        products = list(Product.objects.filter(active=True).order_by("sku"))
        if not orders or not products:
            return []
        rows: list[Any] = []
        for number, order in enumerate(orders):
            left = context.count - len(rows)
            wanted = min(
                1 + number % 3, max(left - (len(orders) - number - 1), 1), left
            )
            for k in range(wanted):
                product = products[(number * 3 + k) % len(products)]
                line = OrderItem.from_product(order, product, k + 1)
                values = {
                    name: getattr(line, name)
                    for name in (
                        "product",
                        "name",
                        "sku",
                        "quantity",
                        "unit_price",
                        "line_total",
                    )
                }
                rows += context.create(1, order=order, **values)
            total = order.items_total()
            payment = payment_for(
                order, total, uuid.UUID(int=context.random.getrandbits(128))
            )
            this = Order.objects.filter(pk=order.pk)
            # the history keeps the status only (audit: [status]): nothing is lost here
            money = {"subtotal": total, "total": total, "payment": payment}
            this.update(**money)  # karni: allow(audited-bulk-write): demo data
            if order.status == "pending":
                order.refresh_from_db()
                try:
                    services.reserve(order)
                except ValidationError:
                    pass  # sold out since: the demo order simply holds nothing
        return rows


def payment_for(order: Order, total: Decimal, pk: uuid.UUID) -> Payment:
    """The order's payment as the test provider would have left it."""
    status = {
        "pending": Payment.Status.PENDING,
        "failed": Payment.Status.FAILED,
        "cancelled": Payment.Status.REFUNDED,
        "refunded": Payment.Status.REFUNDED,
    }.get(order.status, Payment.Status.SUCCEEDED)
    payment = Payment.objects.create(
        id=pk,
        user=order.customer,
        amount=total,
        currency="usd",
        provider="test",
        status=status,
        checkout_session_id=f"seed_cs_{order.number}",
        metadata={"order": str(order.pk), "number": order.number},
    )
    if order.status in ("refunded", "cancelled"):
        Refund.objects.create(
            id=uuid.UUID(int=pk.int ^ 1),
            payment=payment,
            amount=total,
            status=Refund.Status.SUCCEEDED,
            reason=f"order {order.number} {order.status}",
        )
    return payment

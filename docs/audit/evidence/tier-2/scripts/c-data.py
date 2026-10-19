# Claim (c): seed Product rows (JSON, FK, M2M, choices, File, Image, Date, Decimal, Boolean).
import io
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from PIL import Image

from karni.admin import derive
from karni.middleware import current_user
from shop.models import Product, Tag, Venue

User = get_user_model()
alice = User.objects.get(email="alice@example.com")
v = Venue.objects.filter(name="Hall B").first()
t1, _ = Tag.objects.get_or_create(name="sale")
t2, _ = Tag.objects.get_or_create(name="new")
t3, _ = Tag.objects.get_or_create(name="bulky")

buf = io.BytesIO()
Image.new("RGB", (64, 48), (200, 40, 40)).save(buf, format="PNG")
png = buf.getvalue()

with current_user(alice):
    p1 = Product.objects.create(
        name="Steel Kettle", sku="kettle-01", kind="physical", price=Decimal("1299.50"),
        in_stock=True, released_on=date(2026, 3, 1), attributes={"color": "silver", "litres": 1.7}, venue=v,
    )
    p1.tags.set([t1, t3])
    p1.manual.save("kettle-manual.txt", ContentFile(b"Boil water. Do not microwave."), save=False)
    p1.photo.save("kettle.png", ContentFile(png), save=True)
    p2 = Product.objects.create(
        name="E-book: Django Patterns", sku="ebook-dj", kind="digital", price=Decimal("499.00"),
        in_stock=True, released_on=date(2025, 11, 20), attributes={"pages": 310, "format": ["epub", "pdf"]},
    )
    p2.tags.set([t2])
    p3 = Product.objects.create(
        name="Venue cleaning", sku="svc-clean", kind="service", price=Decimal("2500.00"),
        in_stock=False, released_on=None, attributes={}, venue=v,
    )
print("products:", list(Product.objects.values_list("name", "kind", "price", "in_stock", "released_on", "manual", "photo")))
print("tags per product:", {p.name: [t.name for t in p.tags.all()] for p in Product.objects.all()})
print()
print("Derived admin options for Product (karni.admin.derive):")
print("  list_display       :", derive.derive_list_display(Product))
print("  list_filter        :", [f if isinstance(f, str) else (f[0], f[1].__name__) if isinstance(f, tuple) else f.__name__ for f in derive.derive_list_filter(Product)])
print("  search_fields      :", derive.derive_search_fields(Product))
print("  date_hierarchy     :", derive.derive_date_hierarchy(Product))
print("  readonly_fields    :", derive.derive_readonly_fields(Product))
print("  list_select_related:", derive.derive_list_select_related(Product))
from django.contrib import admin as dj_admin
ma = dj_admin.site._registry.get(Product)
print()
print("Registered admin class:", type(ma).__name__, "MRO:", [c.__name__ for c in type(ma).__mro__][:5])
print("  live list_display       :", ma.list_display)
print("  live list_filter        :", [f if isinstance(f, str) else (f[0], f[1].__name__) if isinstance(f, tuple) else f.__name__ for f in ma.list_filter])
print("  live search_fields      :", ma.search_fields)
print("  live date_hierarchy     :", ma.date_hierarchy)
print("  live readonly_fields    :", ma.readonly_fields)
print("  live list_select_related:", ma.list_select_related)
print("  live autocomplete_fields:", ma.autocomplete_fields)
print("  live actions            :", [a if isinstance(a, str) else a.__name__ for a in (ma.actions or [])])
print("  admin.py in shop/?      :", __import__("os").path.exists("shop/admin.py"))
import glob
print("  any admin.py in project :", glob.glob("**/admin.py", recursive=True))
from django.test import RequestFactory
rf = RequestFactory()
req = rf.get("/admin/shop/product/add/")
req.user = User.objects.get(email="root@example.com")
form = ma.get_form(req)()
print()
print("Add-form widgets (field -> widget class):")
for name, field in form.fields.items():
    print(f"  {name:12s} -> {type(field.widget).__name__}" + (f"  [choices={len(list(field.choices))}]" if hasattr(field, 'choices') and not name in ('venue','tags') else ""))
print("DONE C-data")

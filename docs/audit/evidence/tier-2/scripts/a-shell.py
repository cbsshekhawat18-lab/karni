# Claim (a) — exercised through `manage.py shell` in the scratch project.
import uuid

from django.contrib.auth import get_user_model
from django.db import connection, reset_queries
from django.utils import timezone

from karni.middleware import current_user
from shop.models import (
    Event,
    OnlyAudited,
    OnlySoftDelete,
    OnlyTimestamped,
    OnlyUuid,
    Venue,
)

User = get_user_model()


def q(label):
    print(f"\n--- SQL for: {label} ({len(connection.queries)} queries)")
    for row in connection.queries:
        print("   ", row["sql"][:300])
    reset_queries()


def show(obj, *names):
    print(f"{obj.__class__.__name__}: " + ", ".join(f"{n}={getattr(obj, n)!r}" for n in names))


print("=" * 70)
print("A1. BaseModel fields: UUID pk, created_at/updated_at, created_by/updated_by")
alice = User.objects.create_user(email="alice@example.com", password="x")
bob = User.objects.create_user(email="bob@example.com", password="x")
reset_queries()
with current_user(alice):
    venue = Venue.objects.create(name="Hall A", city="Jaipur", capacity=100)
q("Venue.objects.create() under current_user(alice)")
show(venue, "id", "created_at", "updated_at", "deleted_at", "created_by", "updated_by")
print("pk is uuid.UUID:", isinstance(venue.pk, uuid.UUID), "| version:", venue.pk.version)
cols = [f.name for f in Venue._meta.fields]
print("Venue columns:", cols)

with current_user(bob):
    venue.name = "Hall A (renamed)"
    venue.save(update_fields=["name"])
venue.refresh_from_db()
show(venue, "created_by", "updated_by")
print("created_by stays alice, updated_by becomes bob:", venue.created_by == alice and venue.updated_by == bob)
print("updated_at > created_at:", venue.updated_at > venue.created_at)

print("\nA2. Outside a request/current_user: nothing stamped")
v2 = Venue.objects.create(name="Hall B", city="Delhi", capacity=50)
show(v2, "created_by", "updated_by")

print("=" * 70)
print("A3. Soft delete")
with current_user(alice):
    e1 = Event.objects.create(title="Gig 1", starts_at=timezone.now(), venue=venue, organizer=alice)
    e2 = Event.objects.create(title="Gig 2", starts_at=timezone.now(), venue=venue, organizer=alice)
    e3 = Event.objects.create(title="Gig 3", starts_at=timezone.now(), venue=v2, organizer=bob)
reset_queries()
result = e1.delete()
q("e1.delete()")
print("delete() returned:", result)
e1.refresh_from_db()
show(e1, "deleted_at", "is_deleted")
print("Event.objects.count():", Event.objects.count())
print(
    "without('soft_delete').count():",
    Event.objects.without("soft_delete", reason="audit").count(),
)
print(
    "without('soft_delete').dead():",
    list(Event.objects.without("soft_delete", reason="audit").dead().values_list("title", flat=True)),
)
with connection.cursor() as cur:
    cur.execute("SELECT title, deleted_at IS NOT NULL AS deleted FROM shop_event ORDER BY title")
    print("raw table rows:", cur.fetchall())
reset_queries()
print("Event.objects.all() SQL:", str(Event.objects.all().query)[:200])

print("\nA4. Related lookups with soft delete")
reset_queries()
print("venue.event_set.all() titles:", list(venue.event_set.values_list("title", flat=True)))
q("venue.event_set.all()")
print(
    "venue.event_set.without('soft_delete'):",
    list(venue.event_set.without("soft_delete", reason="audit").values_list("title", flat=True)),
)
# prefetch_related also hides deleted rows
vs = list(Venue.objects.prefetch_related("event_set").filter(pk=venue.pk))
print("prefetch_related('event_set') on venue:", [e.title for e in vs[0].event_set.all()])
# FK from child to a soft-deleted parent still resolves
venue.delete()
e2.refresh_from_db()
reset_queries()
print("e2.venue after venue soft-deleted:", repr(e2.venue), "deleted_at set:", e2.venue.deleted_at is not None)
q("e2.venue (forward FK after parent soft delete)")
print("Venue.objects.filter(pk=venue.pk).exists():", Venue.objects.filter(pk=venue.pk).exists())
print("Event.objects.count() after venue soft-delete (no cascade):", Event.objects.count())
print("Event.objects.filter(venue=venue).count():", Event.objects.filter(venue=venue).count())
# restore
venue.restore()
print("after venue.restore(): Venue alive count:", Venue.objects.filter(pk=venue.pk).count())
e1.restore()
print("after e1.restore(): Event.objects.count():", Event.objects.count())

print("\nA5. CASCADE on hard_delete (including soft-deleted children)")
e1.delete()  # soft again
print("before hard_delete: events total (with deleted):",
      Event.objects.without("soft_delete", reason="audit").filter(venue=venue).count())
reset_queries()
res = venue.hard_delete()
q("venue.hard_delete()")
print("hard_delete() returned:", res)
with connection.cursor() as cur:
    cur.execute("SELECT count(*) FROM shop_event")
    print("rows left in shop_event (raw):", cur.fetchone()[0], "(expected 1: Gig 3 at Hall B)")
    cur.execute("SELECT count(*) FROM shop_venue")
    print("rows left in shop_venue (raw):", cur.fetchone()[0])

print("\nA6. Queryset delete is soft; queryset hard_delete is real")
with current_user(alice):
    for i in range(3):
        Event.objects.create(title=f"Bulk {i}", starts_at=timezone.now(), venue=v2)
print("bulk soft:", Event.objects.filter(title__startswith="Bulk").delete())
print("alive bulk:", Event.objects.filter(title__startswith="Bulk").count(),
      "| dead bulk:", Event.objects.without("soft_delete", reason="audit").dead().filter(title__startswith="Bulk").count())
print("bulk hard:", Event.objects.without("soft_delete", reason="audit").filter(title__startswith="Bulk").hard_delete())
with connection.cursor() as cur:
    cur.execute("SELECT count(*) FROM shop_event WHERE title LIKE 'Bulk%%'")
    print("raw rows left for Bulk*:", cur.fetchone()[0])

print("\nA7. Deprecated alias still works and warns")
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    n = Event.all_objects.count()
    print("Event.all_objects.count():", n, "| warnings:", [str(x.message)[:160] for x in w])

print("=" * 70)
print("A8. Each mixin standalone")
u = OnlyUuid.objects.create(label="u")
print("OnlyUuid: pk", repr(u.pk), "type", type(u.pk).__name__, "| fields:", [f.name for f in OnlyUuid._meta.fields])
t = OnlyTimestamped.objects.create(label="t")
print("OnlyTimestamped: pk", repr(t.pk), "| fields:", [f.name for f in OnlyTimestamped._meta.fields],
      "| created_at", t.created_at, "| queryset:", type(OnlyTimestamped.objects.all()).__name__)
print("   created_since works:", OnlyTimestamped.objects.created_since(t.created_at).count())
s = OnlySoftDelete.objects.create(label="s")
print("OnlySoftDelete: pk", repr(s.pk), "| fields:", [f.name for f in OnlySoftDelete._meta.fields])
s.delete()
print("   after delete: objects.count()", OnlySoftDelete.objects.count(),
      "| without:", OnlySoftDelete.objects.without("soft_delete", reason="audit").count(),
      "| is_deleted", OnlySoftDelete.objects.without("soft_delete", reason="audit").get().is_deleted)
s.restore(); print("   after restore: objects.count()", OnlySoftDelete.objects.count())
s.hard_delete(); print("   after hard_delete: without count", OnlySoftDelete.objects.without("soft_delete", reason="audit").count())
with current_user(bob):
    a = OnlyAudited.objects.create(label="a")
print("OnlyAudited: pk", repr(a.pk), "| fields:", [f.name for f in OnlyAudited._meta.fields],
      "| created_by", a.created_by, "| updated_by", a.updated_by,
      "| created_by(bob).count()", OnlyAudited.objects.created_by(bob).count())
print("   hasattr delete-soft?", hasattr(OnlyAudited, "hard_delete"), "(expected False: not a SoftDeleteModel)")

print("=" * 70)
print("A9. Admin with soft-deleted rows (Django test client, superuser)")
from django.test import Client
admin_user = User.objects.create_superuser(email="root@example.com", password="rootpass123")
c = Client()
c.force_login(admin_user)
with current_user(alice):
    gone = Event.objects.create(title="Gone event", starts_at=timezone.now(), venue=v2)
    kept = Event.objects.create(title="Kept event", starts_at=timezone.now(), venue=v2)
gone.delete()
r = c.get("/admin/shop/event/")
body = r.content.decode()
print("changelist status:", r.status_code, "| shows Kept:", "Kept event" in body, "| shows Gone:", "Gone event" in body)
import re
print("deleted filter present:", bool(re.search(r"deleted", body, re.I)), "| filter links:", sorted(set(re.findall(r'\?deleted=([a-z_]+)', body))))
for val in sorted(set(re.findall(r'\?deleted=([a-z_]+)', body))):
    rr = c.get(f"/admin/shop/event/?deleted={val}")
    bb = rr.content.decode()
    print(f"  ?deleted={val}: status {rr.status_code} | Kept: {'Kept event' in bb} | Gone: {'Gone event' in bb}")
r = c.get(f"/admin/shop/event/{gone.pk}/change/")
print("change form of a soft-deleted row:", r.status_code)
# actions available
print("actions offered:", re.findall(r'<option value="([a-z_]+)"', body)[:6])
# restore via action
r = c.post("/admin/shop/event/?deleted=deleted", {"action": "restore_selected", "_selected_action": [str(gone.pk)]}, follow=True)
print("restore_selected status:", r.status_code, "| gone alive now:", Event.objects.filter(pk=gone.pk).exists())
print("venue change form (add) for Event:", c.get("/admin/shop/event/add/").status_code)
print("DONE A")

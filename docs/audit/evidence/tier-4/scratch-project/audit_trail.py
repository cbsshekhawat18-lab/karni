"""Tier 4 audit, item 5: AuditedModel stamps across API / admin / command / shell / update().

Run: python manage.py shell -c "exec(open('<this file>').read())"   (dev DB karni_audit_t4)
"""

import json
import subprocess
import sys

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.test.utils import override_settings
from karni.middleware import current_user

from events.models import Venue

User = get_user_model()
api_user, _ = User.objects.get_or_create(email="api-user@example.com", defaults={"first_name": "Api"})
api_user.set_password("karni-password"); api_user.save()
admin_user, _ = User.objects.get_or_create(
    email="admin@example.com", defaults={"is_staff": True, "is_superuser": True, "first_name": "Admin"}
)
admin_user.is_staff = admin_user.is_superuser = True
admin_user.set_password("karni-password"); admin_user.save()
cmd_user, _ = User.objects.get_or_create(email="cmd-user@example.com")


def stamp(label, pk):
    v = Venue.objects.get(pk=pk)
    print(
        f"{label:<48} name={v.name!r:<22} created_by={getattr(v.created_by, 'email', None)!s:<22} "
        f"updated_by={getattr(v.updated_by, 'email', None)!s:<22} updated_at={v.updated_at.isoformat()}"
    )


# 0. create via the API as api_user (JWT login against the live server on 8541 is in audit-trail-curl.txt;
#    here the in-process client exercises the same view code)
client = Client(HTTP_HOST="127.0.0.1")
client.force_login(api_user)
with override_settings(KARNI_AUTH_MODE="session"):
    r = client.post("/api/venues/", data=json.dumps({"name": "Audit Hall", "city": "Pune"}), content_type="application/json")
    print("POST /api/venues/ ->", r.status_code)
    pk = r.json()["id"]
    stamp("after API create (api-user)", pk)

    # 1. API PATCH as api_user
    r = client.patch(f"/api/venues/{pk}/", data=json.dumps({"name": "Audit Hall v2"}), content_type="application/json")
    print("PATCH /api/venues/<pk>/ ->", r.status_code, "X-Karni-Queries=", r.get("X-Karni-Queries"))
    stamp("after API PATCH (api-user)", pk)

# 2. admin change form as admin_user
admin_client = Client(HTTP_HOST="127.0.0.1")
admin_client.force_login(admin_user)
r = admin_client.get(f"/admin/events/venue/{pk}/change/")
print("GET /admin/events/venue/<pk>/change/ ->", r.status_code)
r = admin_client.post(
    f"/admin/events/venue/{pk}/change/",
    data={"name": "Audit Hall v3 (admin)", "city": "Pune", "_save": "Save"},
)
print("POST /admin/events/venue/<pk>/change/ ->", r.status_code, r.get("Location"))
stamp("after admin change (admin@example.com)", pk)

# 3. management command, without and with current_user()
print("\n$ manage.py audit_touch <pk> 'Audit Hall v4 (command)'")
call_command("audit_touch", str(pk), "Audit Hall v4 (command)")
stamp("after command, no current_user", pk)
print("\n$ manage.py audit_touch <pk> 'Audit Hall v5 (command as cmd-user)' --as-user cmd-user@example.com")
call_command("audit_touch", str(pk), "Audit Hall v5 (command as cmd-user)", as_user="cmd-user@example.com")
stamp("after command with current_user(cmd-user)", pk)

# 4. manage.py shell: plain save, then save inside current_user()
v = Venue.objects.get(pk=pk); v.name = "Audit Hall v6 (shell)"; v.save()
stamp("after shell save(), no current_user", pk)
with current_user(admin_user):
    v = Venue.objects.get(pk=pk); v.name = "Audit Hall v7 (shell as admin)"; v.save()
stamp("after shell save() inside current_user(admin)", pk)

# 5. queryset.update() inside a request-like context: does updated_by/updated_at move?
with current_user(cmd_user):
    before = Venue.objects.get(pk=pk)
    n = Venue.objects.filter(pk=pk).update(name="Audit Hall v8 (queryset.update)")
    print(f"\nVenue.objects.filter(pk=pk).update(name=...) inside current_user(cmd-user): {n} row(s)")
    after = Venue.objects.get(pk=pk)
    stamp("after queryset.update()", pk)
    print("updated_at moved:", after.updated_at != before.updated_at, "| updated_by changed:", after.updated_by_id != before.updated_by_id)

# 6. what a history endpoint / admin tab returns today
r = admin_client.get(f"/api/venues/{pk}/history/")
print("\nGET /api/venues/<pk>/history/ ->", r.status_code, r.content[:160])
r = admin_client.get(f"/admin/events/venue/{pk}/history/")
html = r.content.decode()
print("GET /admin/events/venue/<pk>/history/ ->", r.status_code)
import re
rows = re.findall(r"<td[^>]*>(.*?)</td>", html, flags=re.S)
cleaned = [re.sub(r"<[^>]+>", "", c).strip() for c in rows]
print("admin history table cells:", [c for c in cleaned if c][:12])
print("mentions old value 'Audit Hall v2'?", "Audit Hall v2" in html, "| mentions 'v3 (admin)'?", "v3 (admin)" in html)
from django.contrib.admin.models import LogEntry
for e in LogEntry.objects.filter(object_id=str(pk)).order_by("action_time"):
    print("LogEntry:", e.action_time.isoformat(), e.user.email, "flag=", e.action_flag, "change_message=", e.change_message)
print("\nVENUE_PK=", pk)

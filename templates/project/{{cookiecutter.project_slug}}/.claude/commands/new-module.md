---
description: Create a new local Django app following Karni conventions
---
Create a local app: $ARGUMENTS

1. Run `karni context` first — confirm the domain isn't already covered.
2. Create `<app>/` with only: `__init__.py`, `apps.py` (plain AppConfig),
   `models.py` (BaseModel subclasses), `viewsets.py` (BaseViewSet subclasses).
   No admin.py, serializers.py, urls.py, forms.py — Karni derives all of that.
3. Add the app to the `# karni:apps` block in config/settings.py.
4. `make migrate && karni types`, then `karni context` to verify.
5. Anything reusable across projects belongs in a Karni module
   (karni_<name> package), not in this project — say so instead of building it.

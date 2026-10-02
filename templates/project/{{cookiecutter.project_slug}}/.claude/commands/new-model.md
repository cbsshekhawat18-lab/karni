---
description: Add a domain model the Karni way (model + viewset, nothing else)
---
Add a new domain model: $ARGUMENTS

1. Run `karni context` to see existing models and viewsets.
2. In the owning app's `models.py`, define the model inheriting
   `karni.models.BaseModel` (`SoftDeleteModel` if it needs restore).
   Declare `class APIMeta:` / `class AdminMeta:` only for fields that must be
   hidden, read-only or write-only. Do NOT write an admin, serializer or router.
3. In the same app's `viewsets.py`:
   `class XViewSet(BaseViewSet): model = X` (+ `search_fields` if searchable).
   The auto-router registers it; admin, filters, schema are derived.
4. `make migrate && karni types`
5. Verify: `karni context` lists the model and viewset; GET /api/<plural>/ works.

Total new code should be well under 20 lines. If it isn't, stop — you are
reimplementing something Karni provides.

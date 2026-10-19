---
description: A full CRUD entity end to end in four project files: the model, a viewset with its access rule, the admin that derives itself and a typed React page.
---

# Adding an entity end to end

The whole point of Karni: a full CRUD entity — API, admin, typed frontend —
in under 40 lines of project code. Four files, nothing else.

## 1. Model — `events/models.py` (9 lines)

```python
from django.db import models

from karni.models import BaseModel


class Event(BaseModel):
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(null=True, blank=True)
```

## 2. Viewset — `events/viewsets.py` (7 lines)

```python
from events.models import Event
from karni.api import Access, Authenticated, BaseViewSet


class EventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Authenticated(), write=Authenticated())
    search_fields = ["title"]
```

That's the entire backend. The auto-router serves `/api/events/` with CRUD,
pagination, filtering, ordering, search, throttling and OpenAPI schema; the
admin autodiscovers a fully configured `Event` admin; no serializer, router,
admin or settings code exists anywhere.

`access` is mandatory: it says who may read and who may write, and Karni
compiles it into both the request gate and the row filter. Here any signed-in
user may do both; `Owned("organizer")` (owner-only rows), `HasRole("staff")`
and `Public()` (anonymous reads) cover the usual variations — see
[Access control](api.md#access-control). A viewset without it answers 403 to
everything and fails `karni check`.

## 3. Wire and generate

```
make migrate && karni types
```

## 4. Pages — `frontend/src/pages/` (2 files, ~18 lines)

```tsx
// events.tsx
import { Page, ResourceTable } from "@karni/ui";

export function EventsPage() {
  return (
    <Page title="Events">
      <ResourceTable resource="events" />
    </Page>
  );
}
```

```tsx
// event-edit.tsx
import { Page, ResourceForm } from "@karni/ui";

export function EventEditPage({ id }: { id?: string }) {
  return (
    <Page title={id ? "Edit event" : "New event"}>
      <ResourceForm resource="events" id={id} />
    </Page>
  );
}
```

Register the two routes, done. Total: ~34 lines. Custom behaviour (columns,
field renderers, permissions, actions) is added through props on these same
components — never by rewriting them.

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

## 2. Viewset — `events/viewsets.py` (6 lines)

```python
from events.models import Event
from karni.api import BaseViewSet


class EventViewSet(BaseViewSet):
    model = Event
    search_fields = ["title"]
```

That's the entire backend. The auto-router serves `/api/events/` with CRUD,
pagination, filtering, ordering, search, throttling and OpenAPI schema; the
admin autodiscovers a fully configured `Event` admin; no serializer, router,
admin or settings code exists anywhere.

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

Register the two routes, done. Total: ~33 lines. Custom behaviour (columns,
field renderers, permissions, actions) is added through props on these same
components — never by rewriting them.

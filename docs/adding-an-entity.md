---
description: "A full CRUD entity end to end in four project files: the model, a viewset with its access rule, the admin that derives itself and a typed React page."
---

# Adding an entity end to end

This is the whole point of Karni: a full CRUD entity (API, admin, typed
frontend) in under 40 lines of project code. Four files, nothing else.

## 1. Model: `events/models.py` (9 lines)

```python
from django.db import models

from karni.models import BaseModel


class Event(BaseModel):
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(null=True, blank=True)
```

## 2. Viewset: `events/viewsets.py` (7 lines)

```python
from events.models import Event
from karni.api import BaseViewSet, Granted


class EventViewSet(BaseViewSet):
    model = Event
    access = Granted()
    search_fields = ["title"]
```

That's the entire backend. The auto-router serves `/api/events/` with CRUD,
pagination, filtering, ordering, search, throttling and OpenAPI schema. The
admin autodiscovers a fully configured `Event` admin. No serializer, router,
admin or settings code exists anywhere.

`access` is mandatory: it says who may read and who may write, and Karni
compiles it into both the request gate and the row filter. `Granted()` is
the default `karni make viewset` writes: whatever the project's roles grant
for `Event` (`KARNI_ROLES`), row scope included, so a `user` sees their own
events and `staff` every one without this file saying so. A custom rule
names its predicates, such as
`Access(read=Owned("organizer") | HasRole("staff"), write=Owned("organizer"))`,
or `Public()` for anonymous reads. See
[Access control](api.md#access-control). A viewset without `access` answers
403 to everything and fails `karni check`.

## 3. Wire and generate

```
make migrate && karni types
```

## 4. Pages: `frontend/src/pages/` (2 files, ~18 lines)

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
components, never by rewriting them.

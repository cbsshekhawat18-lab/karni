---
description: "The timeline contract in Karni (experimental): one stream of moments per person and per record, written by hand with timeline.record() or from family events that declare a title, read through GET /api/timeline/ where each entry shows only to callers who may read every record it is about."
---

# Timeline

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `karni.timeline` app and its models (`TimelineEntry`,
    `TimelineLink`), the functions of `karni.timeline` (`record`, `prune`,
    `render`, `parse_option`, `write_from_event`, `live_person`, `connect`,
    `disconnect`, `installed`), the `timeline=` option of `declare()`,
    `GET /api/timeline/` and its `karni.timeline.api` and
    `karni.timeline.access` classes, the admin, the beat entry and the
    `KARNI_TIMELINE_*` settings. They may change in a minor release, and each
    change is in the CHANGELOG. The error codes keep their meaning. The
    contract's version is `karni.timeline.CONTRACT` (1).

A project that holds several parts shows, on a person's page and on a
record's page, what happened to them in every part: a ticket opened, a visit,
a call a CRM logged, a paid order. The timeline keeps one stream of those
moments. Each entry is a title written at the time, about a
[person](people.md) and linked to the records it concerns, so one entry shows
on the person, the order and the deal.

Entries are written two ways:

- **From [family events](family-events.md).** An event whose declaration
  names a timeline title becomes an entry after the publisher commits. No
  part writes timeline code for its events.
- **By hand**, with `timeline.record()`, for what is not an event: a call, a
  note, a meeting.

The timeline is not the change history. [Change history](change-history.md)
records every field change of a record. The timeline records business
moments, in words, and never copies the history.

## Install it

```python
# config/settings.py, above karni_settings(globals())
KARNI_PEOPLE = True

# below it
INSTALLED_APPS += [
    "karni.outbox",
    "karni.timeline",
]
```

Then run `migrate`. The timeline needs the people contract (`karni.E461`
without it) and takes its entries from events through the outbox. Without
`karni.outbox`, `record()` still works and `karni.W460` says that no entry
comes from events.

## Entries from events

Add `timeline=` to an event's declaration:

```python
# helpdesk/events.py
from karni.events import declare

declare(
    "helpdesk.ticket.closed",
    version=1,
    fields={
        "ticket": "the ticket's id",
        "topic": "what the ticket is about",
        "minutes": "minutes the ticket was open",
    },
    person="person",
    timeline="Ticket closed: {topic}",
)
```

Each `helpdesk.ticket.closed` the help desk publishes then writes one entry,
after the commit, through a subscriber the timeline adds for every such
declaration (named `karni.timeline:helpdesk.ticket.closed@v1` in the outbox
and in `karni check`). The entry:

- shows on the timeline of the event's **person** (a merged person is
  followed to the person that stayed) and of its **subject**;
- has the event's name as its **kind** and its prefix as its **source**
  (`helpdesk`);
- keeps the event's id, so a redelivered event writes nothing twice (one
  entry per event and person);
- keeps the declared fields in `data`, and the event's actor when that user
  still exists.

An event with neither a known person nor a subject writes nothing.

`timeline=` takes a title template, or a mapping for more:

```python
timeline={
    "title": "Ticket closed: {topic}",
    "body": "Closed after {minutes} minutes.",
    "subjects": {"queue": "helpdesk.queue"},
    "kind": "helpdesk.ticket.closed",
}
```

| Key | What |
|---|---|
| `title` | The title template (required). |
| `body` | A body template. |
| `subjects` | `{field: "app_label.model"}`: declared fields that hold the id of another record the entry shows on. |
| `kind` | The entry's kind, when it is not the event's name. |

A template takes declared fields by their plain name, `{topic}`, as text (a
null value is empty, `{{` and `}}` are braces). Attributes, indexes,
conversions and format specs are refused, as is a field the event does not
declare: `karni check` fails with `karni.E460` and names the declaration. The
title is cut at 300 characters.

The people contract's own events write these entries:

| Event | Title |
|---|---|
| `people.person.linked` | Account linked |
| `people.person.merged` | Merged with a duplicate record |
| `people.organisation.merged` | Merged with a duplicate record (on the organisation) |

karni-payments' `payments.payment.succeeded` writes "Payment of {amount}
{currency} succeeded" on the payer's timeline when the payment's user is
linked to a person.

## Entries by hand: `timeline.record`

```python
from karni import timeline

timeline.record(
    kind="crm.call",
    title="Called about the renewal",
    person=contact,
    subjects=[deal, contact.organisation],
    body=notes,
)
```

Call it inside the transaction of the change it reports. It returns the
entry, or `None` when `karni.timeline` is not installed, so a part calls it
whether or not the project keeps a timeline.

| Argument | What |
|---|---|
| `kind` | What happened: lower-case words joined by dots, the part first (`crm.call`). |
| `title` | One line of plain text, written now. |
| `person` | The person it is about: a `people.Person` or its id. |
| `subjects` | The other records it shows on: model instances or `("app_label.model", id)` pairs. |
| `body` | More text. |
| `occurred_at` | When it happened (default: now). |
| `actor` | The user who acted, their id, or `None` (default: the request's user). |
| `source` | The part that wrote it (default: the first word of `kind`). |
| `data` | JSON values to keep with the entry (a decimal or a date becomes text). |
| `event_id` | The family event it reports: a second call for the same event and person returns the first entry. |

An entry needs a person or a subject. A bad argument is `karni.E462`.

## Read a timeline: `GET /api/timeline/`

```text
GET /api/timeline/?person=<id>
GET /api/timeline/?organisation=<id>
GET /api/timeline/?subject=helpdesk.ticket:<id>
```

```json
{
  "results": [
    {
      "id": "6c1d...",
      "occurred_at": "2026-11-13T09:12:00+00:00",
      "kind": "helpdesk.ticket.closed",
      "title": "Ticket closed: Printer jam",
      "body": "Closed after 42 minutes.",
      "source": "helpdesk",
      "actor": 3,
      "actor_name": "Ines Duarte",
      "person": "1f0e...",
      "event": "8a7d...",
      "links": [{"model": "helpdesk.ticket", "id": "41b2...", "resource": "tickets"}],
      "data": {"ticket": "41b2...", "topic": "Printer jam", "minutes": 42}
    }
  ],
  "next": "MjAyNi0xMS0xM1Qw..."
}
```

- **Whose timeline.** `?person=` lists the entries about that person.
  `?organisation=` and `?subject=<app_label.model>:<id>` list the entries
  linked to that record. Name exactly one of them, else 400 `E463`. The
  record must be one the caller may read, else 404, so the endpoint never
  says whether a record exists. The caller must be signed in.
- **Who sees an entry.** An entry shows only when the caller may read its
  person and every record it is linked to. Each record is checked through
  the queryset its model's own list endpoint uses for the request (the
  routed `BaseViewSet`'s gate, then its row scope), the way
  [cross-model search](global-search.md) does: one query per model on the
  page. A customer sees their own ticket's entry and never the call that
  also concerns someone else's order. A model that no routed viewset serves
  is readable by superusers only, so the people endpoints must be routed
  (`KARNI_PEOPLE_API`) for entries about a person to show to other callers.
- **Paging.** Newest first. `?limit=` entries per page
  (`KARNI_TIMELINE_PAGE_SIZE`, 25, at most `KARNI_TIMELINE_MAX_PAGE_SIZE`,
  100). `next` is the cursor of the following page (`?cursor=`), or null on
  the last one. Entries the caller may not see are skipped, so a page may
  hold fewer than `limit`. The queries of a page grow with the number of
  models its entries link to, not with the number of entries.
- **Filters.** `?kind=` keeps the given kinds and `?source=` the given parts,
  each comma-separated.
- **Links.** Each link names the model, the id and the API resource that
  serves it (null when none does), so a client links to the record's page.

## Merge, erase and retention

- **Merge.** `people.merge()` moves a person's entries and every link to the
  merged person or organisation, like every other reference to it.
- **Erase.** `people.erase()` deletes every entry about the person and every
  entry linked to them: their titles were written with the person's details.
- **Retention.** Entries are kept for ever by default. Set
  `KARNI_TIMELINE_RETENTION_DAYS` and the beat entry `karni-timeline-prune`
  deletes older entries every day. `timeline.prune(days, kinds=[...])` does
  it by hand for some kinds only.

## The admin

*Timeline entries* lists every entry, newest first, with its person, kind,
part and actor, filtered by part and kind and searched by title, person and
event id. Each entry's page shows the records it is linked to. Entries are
not edited by hand. A wrong one can be deleted.

## Settings

| Setting | Default | What |
|---|---|---|
| `KARNI_TIMELINE_API` | `True` | route `GET /api/timeline/` |
| `KARNI_TIMELINE_FROM_EVENTS` | `True` | write entries from events that declare `timeline=` |
| `KARNI_TIMELINE_PAGE_SIZE` | `25` | entries per page |
| `KARNI_TIMELINE_MAX_PAGE_SIZE` | `100` | the largest `?limit=` |
| `KARNI_TIMELINE_RETENTION_DAYS` | `None` | days an entry is kept, `None` for ever |
| `KARNI_TIMELINE_VISIBILITY` | `"karni.timeline.access.Visibility"` | the class that says which records a request may read |

## Escape hatches

- **`timeline=` per event**, or none: an event without it writes no entry.
- **`record()` by hand**, for anything the option cannot say. With
  `KARNI_TIMELINE_FROM_EVENTS = False`, write every entry from a subscriber
  of your own.
- **`KARNI_TIMELINE_VISIBILITY`** names a subclass of
  `karni.timeline.access.Visibility`: override `readable(model, ids)` for one
  model's rule, or `unrouted(model)` for models without an endpoint.
- **`TimelineView`** (`karni.timeline.api`): subclass it
  (`base_queryset`, `serialize`, `visibility`) and mount it yourself with
  `KARNI_TIMELINE_API = False`.

## What it does not do

- It draws nothing. A frontend reads `GET /api/timeline/`.
- It does not show a record's change history next to its entries.
- It does not edit an entry after it is written.

---
description: karni trace follows one request through its Celery tasks, retries, email, webhooks and change log. karni replay re-runs it against the current code as any user, and karni explain --failure turns a crash into a brief.
---

# Trace, replay and failure briefs

Three commands read the [development capture](capture.md): they need
`DEBUG` on when the request ran, and nothing else. Each takes `last` for the
newest capture, and `--json` for agents. They run in the project's
interpreter (its `.venv`, else the running compose service), like every
runner. The same three are MCP tools on `karni mcp` (`trace`, `replay`,
`explain_failure`).

The output below is real: EventHub (`examples/eventhub`) on SQLite with
`KARNI_CACHE=locmem`, a Celery worker on kombu's filesystem broker, an
attendee paying for a booking while the provider's webhook races ahead of
the checkout.

## `karni trace <request-id>`

Every response carries `X-Request-ID`. Pass it (or `last`) and Karni prints
everything that carried that id, in order: the request, the Celery tasks it
enqueued, their retries minutes later, email, webhooks, change-log entries
(read from the database when it is reachable, and from the files alone otherwise).

```
$ karni trace 0caa83ad-4e00-4135-bb12-dbe23bad6ca1
Request 0caa83ad-4e00-4135-bb12-dbe23bad6ca1: POST /payments/webhook/test/ -> 200 in 75.473 ms, as anonymous
  view  karni_payments.webhooks.webhook
  started 2026-10-21 10:34:19 UTC

     +0.000s  request.start     POST /payments/webhook/test/
     +0.049s  task.enqueued     karni_payments.tasks.process_webhook_event [974694c5]
     +0.072s  webhook.received  provider=test event_id=evt_demo_1 event_type=checkout.session.completed duplicate=False refs=karni_payments.WebhookEvent:c5a247ba-…
     +0.076s  request.end       200 in 75.473 ms
     +0.081s  task.started      karni_payments.tasks.process_webhook_event [974694c5] (pid 45087)
     +0.109s  task.enqueued     karni_payments.tasks.process_webhook_event [974694c5] retry 1 eta 2026-10-21T10:34:21.083220+00:00
     +0.117s  task.retried      karni_payments.tasks.process_webhook_event [974694c5]: Retry in 1s: UnmatchedWebhookEventError('Webhook event test:evt_demo_1 (checkout.session.completed) matches no local Payment. It will be retried.')
     +1.115s  task.started      karni_payments.tasks.process_webhook_event [974694c5] retry 1 (pid 45087)
     +1.142s  webhook.matched   provider=test event_id=evt_demo_1 event_type=checkout.session.completed refs=karni_payments.Payment:990fbd5c-…,karni_payments.WebhookEvent:c5a247ba-…
     +1.154s  task.enqueued     events.listeners.send_booking_confirmation [378e08b3]
     +1.205s  task.succeeded    karni_payments.tasks.process_webhook_event [974694c5] in 90.246 ms
     +1.228s  task.started      events.listeners.send_booking_confirmation [378e08b3] (pid 45087)
     +1.232s  task.succeeded    events.listeners.send_booking_confirmation [378e08b3] in 4.099 ms

Linked requests (their events name the same rows):
  78c906a5-857f-4a1f-8836-826ea15012a9  POST /api/bookings/3c82f75e-…/pay/  payment.checkout  [karni_payments.Payment:990fbd5c-…]
```

The webhook's task ran in the worker (its pid), failed to find the payment,
retried a second later under the same id, matched the payment the checkout
request created, and queued the confirmation listener. *Linked requests*
come from shared refs: the checkout named the same payment. Following it:

```
$ karni trace 78c906a5-857f-4a1f-8836-826ea15012a9
Request 78c906a5-857f-4a1f-8836-826ea15012a9: POST /api/bookings/3c82f75e-…/pay/ -> 200 in 56.722 ms, as attendee@example.com
  view  events.viewsets.BookingViewSet (events-booking, pay)
  started 2026-10-21 10:34:20 UTC

     +0.000s  request.start     POST /api/bookings/3c82f75e-…/pay/
     +0.025s  payment.checkout  provider=test amount=50.00 currency=usd refs=karni_payments.Payment:990fbd5c-…
     +0.035s  task.enqueued     events.listeners.send_booking_confirmation [9643a5fc]
     +0.056s  request.end       200 in 56.722 ms
     +0.765s  task.started      events.listeners.send_booking_confirmation [9643a5fc] (pid 45087)
     +0.826s  email.sent        to attendee@example.com "Your tickets for Open Source Summit"
     +0.829s  task.succeeded    events.listeners.send_booking_confirmation [9643a5fc] in 65.041 ms
```

The email went out with `X-Karni-Request-ID: 78c906a5-…`. Change-log entries
of audited models appear in the same timeline (`audit.change`, `audit.batch`).
With no capture, `karni trace` says so and how to enable it (`E921`).

## `karni replay <request-id> [--as <user>]`

Re-sends the captured method, path, query, body and plain headers through
Django's test client, in-process (no server), force-authenticated as the
captured user or `--as` someone else (an email, a username or a primary
key, or `--anonymous` for none). It runs against the **current** code, so no
restart is needed after an edit. It prints the status, a short redacted body excerpt
and what changed against the captured status.

```
$ karni replay 9788cc05-6397-46b8-9834-4b0c7467f75f
Replayed GET /api/events/2369b584-…/dashboard/ as attendee@example.com (rolled back)
  same as captured (403)
  body: {"detail":"Access denied: this row is readable but the action requires Owned('organizer') | HasRole('staff')."}
  new request 50903b6a-b0ff-45ec-b13a-7b9ff91fb358: karni trace 50903b6a-b0ff-45ec-b13a-7b9ff91fb358

$ karni replay 9788cc05-6397-46b8-9834-4b0c7467f75f --as organizer@example.com
Replayed GET /api/events/2369b584-…/dashboard/ as organizer@example.com (rolled back)
  was 403, now 200
  body: {"bookings":3,"tickets":5,"capacity":120,"revenue":"255.00"}
  new request e4fd02cd-e569-4678-b1a2-1ac805c58fc7: karni trace e4fd02cd-e569-4678-b1a2-1ac805c58fc7
```

**Writes are rolled back by default.** The replay runs inside
`transaction.atomic()` on every database and rolls back: `on_commit` work
(queued listeners, webhook tasks) is discarded, mail goes to Django's
in-memory backend and is listed (`email (not sent): to …`) instead of
sent, and a task the view enqueues directly runs eagerly inside the same
transaction. Calls the view makes to outside services are not contained.
`--commit` keeps the writes and uses the real mail backend and broker.

**Redacted values cannot be replayed.** The capture never stored the
password. Replaying the literal `"[redacted]"` could set a password to it,
so the replay stops and names what to supply:

```
$ karni replay 72f5ccf4-068e-4804-8eec-5084b1a10468
error: E923: These values were redacted when the request was captured, so they cannot be replayed: password. Supply them (--set password=<value>) or leave them out (--drop-redacted). See https://cbsshekhawat18-lab.github.io/karni/errors/#e923

$ karni replay 72f5ccf4-068e-4804-8eec-5084b1a10468 --set password=wrong-one
Replayed POST /api/auth/login/ as anonymous (rolled back)
  was 200, now 401
  body: {"detail":"No active account found with the given credentials"}
  new request 6ac58d6c-ed48-4d0b-b535-ddd268ae2380: karni trace 6ac58d6c-ed48-4d0b-b535-ddd268ae2380
```

`--set` takes a dotted body path (`card.token=tok_1`) or `query:<name>`.
The value is parsed as JSON when it can be. Credential headers are never
replayed (the client is force-authenticated), and uploaded files are not
captured, so a multipart replay sends the fields only. `karni replay`
refuses with `DEBUG` off (`E920`): it acts as any user on the configured
database.

## `karni explain --failure <id>`

An unhandled exception writes a failure snapshot. Its id is on the request
record and in `karni trace`. `karni explain --failure` (a failure id, the
failed request's id, or `last`) prints it as a brief. Read it before the
traceback:

```
$ karni explain --failure last
Failure 9a434564036b: GET /api/events/ff9ab5c2-…/dashboard/ by organizer@example.com (id 16419f82-…; roles organizer)
  at 2026-10-21T10:35:50.933316+00:00  request 6247f4b2-bc14-47ce-83db-97557ddf9d00

Exception: TypeError: unsupported operand type(s) for /: 'NoneType' and 'NoneType'
Karni code: none

Where: events/viewsets.py:51 in EventViewSet.dashboard (project)
    51 | "per_ticket": f"{totals['revenue'] / totals['tickets']:.2f}",
  locals:
    self = <events.viewsets.EventViewSet object at 0x10e7d6990>
    request = <Request GET /api/events/ff9ab5c2-…/dashboard/>
    pk = ff9ab5c2-9f04-4aed-b552-332702627f73
    event = {"__model__": "events.Event", "pk": "ff9ab5c2-…", "id": "ff9ab5c2-…", "created_at": "2026-09-18T10:27:00+00…
    confirmed = <QuerySet events.Booking, not evaluated>
    totals = {"tickets": null, "revenue": null}
    capacity = 120
  call path (project and Karni frames, outermost first):
    karni/api/viewsets.py:846 in BaseViewSet.dispatch
    events/viewsets.py:51 in EventViewSet.dashboard

View: events.viewsets.EventViewSet (resource events-event, action dashboard)
  serializer karni.api.serializers.EventsEventSerializer
  kwargs {"pk": "ff9ab5c2-9f04-4aed-b552-332702627f73"}
Grants: none on this resource

Queries: 7 in 0.847 ms, 0 repeated statements

Next steps:
  1. Open events/viewsets.py:51 (EventViewSet.dashboard): it raised there.
  2. After the fix: `karni replay 6247f4b2-bc14-47ce-83db-97557ddf9d00 --as organizer@example.com` re-runs this request against the current code (was 500).
  3. `karni trace 6247f4b2-bc14-47ce-83db-97557ddf9d00` shows what else the request set in motion.
```

An event with no confirmed bookings makes both totals `None`. After the
fix:

```
$ karni replay 6247f4b2-bc14-47ce-83db-97557ddf9d00
Replayed GET /api/events/ff9ab5c2-…/dashboard/ as organizer@example.com (rolled back)
  was 500, now 200
  body: {"bookings":0,"tickets":0,"capacity":120,"revenue":"0.00"}
  new request 73eb70e4-be4e-4327-a77c-a11ddfaa958d: karni trace 73eb70e4-be4e-4327-a77c-a11ddfaa958d
```

The brief adds the Karni code and `karni explain <code>` when the exception
carries one, a hint for common database errors (a missing table: `karni
migrate`), and the N+1 suspects when statements repeated. A Celery task that
fails for good gets a snapshot too (its arguments by parameter name,
redacted like everything else). `karni explain E104` is unchanged. Pass a
code or `--failure`, not both (`C320`).

## Codes

| Code | Meaning |
|---|---|
| `E920` | `karni replay` needs `DEBUG` on |
| `E921` | nothing was captured for this request id (or it is not an id) |
| `E922` | no failure snapshot with this id |
| `E923` | a redacted value must be supplied with `--set` (or `--drop-redacted`) |
| `E924` | the user to replay as cannot be found |
| `W920` | `RequestIdMiddleware` runs after django-structlog's `RequestMiddleware` |
| `C320` to `C323` | the CLI side: `explain` usage, a malformed `--set`, a project karni without these commands, an uncoded failure |

Each is explained by `karni explain <code>` and in [error codes](../errors.md).

---
description: "The notifications contract in Karni (experimental): message kinds on karni.mail sent to an email, the recipient's inbox in the app or both, emails a business edits in the app, each person's own switches, unsubscribing from marketing emails by a signed link, and one sender from the business's details."
---

# Notifications

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `karni.notify` app and its models (`EmailTemplate`, `Notification`,
    `Choice`, `Unsubscribe`), the names of `karni.notify` (`send`, `Sent`,
    `Recipient`, `recipients`, `holders`, `on_event`, `choices`, `choose`, `unsubscribe`,
    `resubscribe`, `unsubscribed`, `unsubscribe_url`, `unread_count`,
    `mark_read`, `mark_unread`, `prune`, `installed`), `karni.notify.source`,
    `karni.notify.adopt`, the `channels=` and `replace=` arguments of
    `karni.mail.register_kind`, `/api/inbox/`, `/api/email-templates/`,
    `/api/notify/unsubscribe/`, the admin, the `features.notify` key of
    karni.yaml and the `KARNI_NOTIFY_*` settings. They may change in a minor
    release, and each change is in the CHANGELOG. The error codes keep their
    meaning. The contract's version is `karni.notify.CONTRACT` (1).

A project of several parts sends one set of messages: an order is paid, a
booking is confirmed, a ticket is closed. Notifications give them one path:

- **Message kinds.** Each part declares the messages it sends, with the merge
  fields a business may use, and whether each goes to an email, to the
  recipient's inbox in the app, or to both.
- **Emails a business edits.** Settings, Emails lists every kind. An email
  rewritten there wins over the template files.
- **The inbox.** A notification per recipient, read or unread, with an API
  for the list, the unread count and marking them read.
- **Switches.** Settings, Emails turns a kind off for the whole project. A
  person turns a kind off for themselves, per channel.
- **Unsubscribe.** A marketing email carries a signed link, and an address
  that left a kind gets no more of it from any part.
- **One sender.** The `From` and the `Reply-To` come from the business's
  details ([preferences](preferences.md)).

## Install it

```python
# config/settings.py, below karni_settings(globals())
INSTALLED_APPS += ["karni.notify"]
```

Then run `migrate`. In a project built from karni.yaml, `features: {notify:
true}` writes the same, and a recipe whose `recipe.toml` has `requires =
["notify>=1"]` switches it on when it is added (the shop does).

Install `karni.preferences` too for the switches in Settings, Emails and the
sender in the details. Without it every kind is on and the sender is
`DEFAULT_FROM_EMAIL`.

## Declare a message kind

In the part's own `<app>/messages.py` (imported the first time `karni.mail`
lists its kinds):

```python
from karni.mail import register_kind

register_kind(
    "desk.ticket_closed",
    title="Ticket closed",
    template="desk/email/ticket_closed",
    audience="the person who opened it",
    describe="The ticket is closed, with the answer.",
    fields={
        "ticket.number": "The ticket's number",
        "ticket.answer": "The answer staff wrote",
        "link": "The ticket's page",
    },
    channels=("email", "inbox"),
)
```

| Argument | Meaning |
|---|---|
| name | `<prefix>.<message>`, a stable name. It goes out in the `X-Karni-Kind` header. |
| `title`, `describe`, `audience` | What Settings, Emails shows. |
| `template` | The stem of the files: `<stem>_subject.txt`, `<stem>_body.txt` and an optional `<stem>_body.html`. |
| `fields` | Each merge field (a dotted path into the context) and what it means. An edited email sees these and nothing else. A meaning that starts with "Each" is one per row (`lines.name`). |
| `channels` | `("email",)` (the default), `("inbox",)` or both. Another name is refused (`E445`). |
| `transactional` | `True` (the default): a receipt, a confirmation. `False` is marketing: it carries an unsubscribe link. |
| `switchable` | `False` for a message nobody may switch off (a sign-in code). |
| `sample`, `samples` | What the editor's preview renders with: the latest matching record, else these values. |
| `replace` | `False` keeps a declaration of the same name that is already there. |

## Send it

```python
from karni import notify

notify.send(
    "desk.ticket_closed",
    to=[ticket.opened_by],
    context={"ticket": ticket, "link": f"/desk/tickets/{ticket.pk}"},
)
```

`to` takes users, people of [karni.people](people.md), email addresses, or a
list of them. A user gives its email and its inbox. A person gives its email,
and its inbox when it has an account. An address reaches the inbox of the
active account with that email. Anything else is refused (`E443`), and so is
a kind nobody declared (`E440`). `notify.holders("shop-manager")` gives the
active users who hold a role, for a message to the staff:
`to=notify.holders("shop-manager", "shop-staff")`.

`send()` returns `Sent(email=..., inbox=...)`: the emails sent and the inbox
rows written. On each channel the kind declares and the project sends on
(`KARNI_NOTIFY_CHANNELS`):

- **email**: one message to every address that wants it, rendered from the
  files or from the edited text. A marketing kind goes to one address at a
  time, with `unsubscribe_url` in its context and the `List-Unsubscribe` and
  `List-Unsubscribe-Post` headers, so a mail program offers one-click
  unsubscribe.
- **inbox**: one notification per recipient with an account. Its title is
  the rendered subject, its body the rendered text, and its link the
  `link=` argument or the context's `link`.

Send after the commit, as for any email (`transaction.on_commit`), so a
rolled-back change tells nobody. Inside `with karni.mail.silenced():` nothing
is sent and no notification is written.

**A part that already sends with `karni.mail` keeps its call.**
`send_templated(template, to=[...], context=..., kind="commerce.order_paid")`
goes through the same path while `karni.notify` is installed: the switches,
the unsubscribes and the edited text hold, and a kind declared on the inbox
lands there too. A kind nobody declared still goes by email only, as before.

**From a family event.** In the part's `listeners.py`:

```python
from karni import notify
from karni.people.models import Person

notify.on_event(
    "desk.ticket.closed",
    "desk.ticket_closed",
    to=lambda event: Person.objects.filter(pk=event.person),
    context=lambda event: {"ticket": {"number": event["number"]}, "link": event["link"]},
)
```

It subscribes to the [family event](family-events.md) by name, and a
redelivered event sends nothing twice. `event.person` is the person's id, so
`to` looks the person up. Without `context`, the message renders with the
event's declared fields.

## Who gets it

In this order, each over the one before:

1. A kind switched off for the project (Settings, Emails, or
   `KARNI_MAIL_DISABLED_KINDS`) goes nowhere.
2. A channel the project leaves out of `KARNI_NOTIFY_CHANNELS` is not used.
3. An address that unsubscribed from a marketing kind gets nothing more of
   it, on any channel, from any part. The unsubscribe is kept by address, so
   a guest with no account is honoured too.
4. A person's own switch turns a switchable kind off for them, per channel.

A kind declared `switchable=False` ignores 3 and 4.

## Emails a business edits

Settings, Emails lists every kind with an Edit button. `/api/email-templates/`
is its API, the same shape the `EmailTemplateEditor` of @karni/ui reads:

| Request | Answer |
|---|---|
| `GET /api/email-templates/` | Every kind: its title, audience, switch, channels, whether it is marketing, its merge fields, and its subject and text now (edited, else the files). |
| `GET /api/email-templates/<kind>/` | One kind, the same way. 404 for a name nobody declared. |
| `PUT /api/email-templates/<kind>/` | `{"subject": ..., "text": ...}`: keep an edit. |
| `DELETE /api/email-templates/<kind>/` | Back to the files. |
| `POST /api/email-templates/<kind>/preview/` | A draft rendered with real values: the business's details and the latest matching record, else the kind's samples. |

Reading needs `notify.emailtemplate:view`, changing `notify.emailtemplate:change`
(the shop's `shop-manager` holds `notify.emailtemplate:*`).

An edit is kept in `EmailTemplate` and wins over the files, for the email and
for the inbox. It renders with a restricted engine: the declared merge fields
only, as plain values, and no tag that loads code or another template
(`{% load %}`, `{% include %}` and `{% extends %}` are refused when it is
saved, 400).

## The emails of moves

A move that names a recipient in karni.yaml (`moves: {confirmed: {notify:
guest}}`, [rules](rules.md#moves)) sends its email through notifications. It
is a kind named `<app>.<model>_<state>` (`bookings.booking_confirmed`) with
the merge fields `row`, `model`, `state`, `recipient.first_name`,
`recipient.email` and `frontend`, so Settings, Emails lists it, a business may
rewrite it, and the recipient may switch it off for themselves. It goes to
the email and the inbox (`KARNI_NOTIFY_MOVE_CHANNELS`). A part that declares
the same name in its `messages.py` wins.

## The inbox API

Every route answers the signed-in person about their own notifications only.

| Request | Answer |
|---|---|
| `GET /api/inbox/` | The newest first: `{"count", "unread", "next", "results"}`. `?unread=true`, `?kind=a,b`, `?limit=` (up to `KARNI_NOTIFY_MAX_PAGE_SIZE`) and `?page=` from 1. A page past the last is 400 `E444`. |
| `GET /api/inbox/unread/` | `{"count": 3}`, for the bell. |
| `POST /api/inbox/<id>/read/` | The notification, read. 404 for another person's. |
| `POST /api/inbox/<id>/unread/` | The notification, unread again. |
| `POST /api/inbox/read-all/` | `{"updated": 3}`. |
| `GET /api/inbox/choices/` | Each kind the person may switch: its title, whether it is marketing, its channels, and `email` and `inbox` as they are for them now. |
| `PATCH /api/inbox/choices/<kind>/` | `{"email": false}`, `{"inbox": false}` or both. A kind nobody may switch is 400 `E441`. Turning a marketing kind's email on again takes back the unsubscribe of their address. |

Notifications older than `KARNI_NOTIFY_RETENTION_DAYS` (180 by default), read
or not, are deleted by a daily task. `notify.prune(days)` does it by hand.

## The unsubscribe link

A marketing email links to `KARNI_FRONTEND_URL` plus
`KARNI_NOTIFY_UNSUBSCRIBE_PATH`, with a token signed with the project's
`SECRET_KEY` that names the address and the kind. The default path is the
API's own page, which needs no sign-in:

- `GET /api/notify/unsubscribe/?token=...` says what the link unsubscribes,
  as a small page in a browser (`karni/notify/unsubscribe.html`, which a
  project overrides in its templates) or as JSON. A GET never unsubscribes,
  so a link scanner cannot.
- `POST` with the token unsubscribes: the page's button, or a mail program's
  one-click. `&undo=1` takes it back.
- A token this project did not sign is 400 `E442`.

Point `KARNI_NOTIFY_UNSUBSCRIBE_PATH` at a page of your own app
(`/unsubscribe?token={token}`) that posts to the API.

## The admin

Edited emails (checked by the restricted engine before they are saved),
Notifications (read only: parts write them, and a wrong one may be deleted),
Choices and Unsubscribes (a person who asks by phone can be helped).

## A part's own table of edited emails

A part that kept edited emails in a table of its own hands them over in a
data migration with `karni.notify.adopt.adopt_edited_emails(apps, schema_editor,
"<app>.<Model>")`: each live row is copied to `EmailTemplate` with its dates
and authors, unless the contract already holds an edit of that kind. Without
`karni.notify` installed, a table with edits stops the migration (`E446`)
before the part drops it. karni-commerce's migration 0006 does this.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `KARNI_MAIL_SOURCE` | `"karni.notify.source.NotifySource"` | What `karni.mail` asks: edited emails, the switches, the sender and the delivery. Blank: `karni.mail.DefaultSource` (the files and the preferences' switches, email only). |
| `KARNI_NOTIFY_API` | `True` | Mount `/api/inbox/`, `/api/email-templates/` and `/api/notify/unsubscribe/`. |
| `KARNI_NOTIFY_CHANNELS` | `["email", "inbox"]` | The channels the project sends on. |
| `KARNI_NOTIFY_PAGE_SIZE` | `25` | Notifications per page of `GET /api/inbox/`. |
| `KARNI_NOTIFY_MAX_PAGE_SIZE` | `100` | The largest `?limit=`. |
| `KARNI_NOTIFY_RETENTION_DAYS` | `180` | Days a notification is kept. `None` keeps them all and schedules nothing. |
| `KARNI_NOTIFY_UNSUBSCRIBE_PATH` | `"/api/notify/unsubscribe/?token={token}"` | Where an unsubscribe link points, after `KARNI_FRONTEND_URL`. |
| `KARNI_NOTIFY_MOVE_CHANNELS` | `["email", "inbox"]` | Where a move's email goes. |

`karni check` warns (`W440`) about a kind whose channels are all left out of
`KARNI_NOTIFY_CHANNELS`, because it goes nowhere.

## Escape hatches

- A template of the same name earlier in `TEMPLATES` `DIRS` changes a
  message without code. An edit in Settings, Emails wins over both.
- `KARNI_MAIL_SOURCE` names a subclass of `NotifySource` (or any object with
  `template(kind)`, `enabled(kind)`, `sender()` and `send(...)`).
- `KARNI_NOTIFY_API = False`, then `build_urlpatterns(force=True)` from
  `karni.notify.api` in a URLconf of your own, and subclass the views and
  `karni.notify.viewsets.EmailTemplateViewSet`.
- A model's `notify_move(key)` replaces the sending of its move emails.
- The models are plain Django models: read them in reports, export them.

## What it does not do

- It renders no page. The bell in the layout, the `/inbox` page and a
  person's email switches on their account page are built on this API in
  @karni/ui.
- It sends no text messages and no push notifications: the channels are an
  email and the inbox.
- It does not group messages into a digest.
- karni-approvals, karni-site and karni-impersonation still send their own
  emails their own way. Moving them onto message kinds is planned, with a
  deprecation cycle.
- The kinds karni-commerce and the shop declare go to the email only. A part
  that wants one in the inbox declares it with `channels=("email", "inbox")`.

## Errors

| Code | When |
|---|---|
| `E440` | `notify.send()` with a kind nobody declared. |
| `E441` | Switching a kind nobody may switch, or unsubscribing from one that is not marketing. |
| `E442` | An unsubscribe token this project did not sign. |
| `E443` | A recipient that is not a user, a person or an address. |
| `E444` | An inbox page that does not exist. |
| `E445` | A kind declared on a channel that is not `email` or `inbox`. |
| `E446` | Edited emails a part hands over, and `karni.notify` is not installed. |
| `W440` | A kind declared on channels the project does not send on. |

Each is explained in [the error reference](errors.md).

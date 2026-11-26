---
description: "The preferences contract in Karni: the business's details, one settings section per part as a Pydantic model, values a deployment locks, connections that switch on when what they need is installed, email switches, and the API behind the Settings page."
---

# Preferences

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `karni.preferences` app and its models (`Details`, `SectionValue`,
    `Switch`), the names of `karni.preferences` (`Section`, `section`,
    `connection`, `email`, `value`, `get`, `details`, `sender`, `active`,
    `email_on`, `save_details`, `save_section`, `switch`, `can_change`,
    `override`, `PreferenceRefused`), `/api/preferences/`, the admin, the
    `features.preferences` key of karni.yaml and the `KARNI_PREFERENCES_*`
    settings. They may change in a minor release, and each change is in the
    CHANGELOG. The error codes keep their meaning. The contract's version is
    `karni.preferences.CONTRACT` (1).

A business changes some things without code: its name and address, who its
emails come from, how long a member may cancel, whether a closed ticket goes on
the timeline. Preferences keeps them in one place, with one Settings page for
the whole project:

- **Details**: the business's name, legal name, address, phone, contact email,
  tax number (for invoices), the sender of its emails (name, address, reply-to), logo, time zone,
  language, currency and how money shows it.
- **One section per part.** Each part declares its settings as a Pydantic
  model, with defaults and the role that may change them.
- **Connections.** What happens because two things are installed together
  ([the family](family.md)), each with a switch.
- **Emails.** A switch per email the project sends.
- **Locks.** A value the deployment fixes. Settings shows it and does not let
  anyone change it.

Every change is audited ([change history](change-history.md)): who changed
what, from what, to what.

## Install it

```python
# config/settings.py, below karni_settings(globals())
INSTALLED_APPS += ["karni.preferences"]
```

Then run `migrate`. In a project built from karni.yaml,
`features: {preferences: true}` writes the same, and a recipe whose
`recipe.toml` has `requires = ["preferences>=1"]` switches it on when it is
added. The build also writes `KARNI_PREFERENCES_DEFAULTS` with the project's
name from karni.yaml, so the details start filled in, and
`KARNI_PREFERENCES_LOCKED` with its currency (`app.currency`): every money
field is in that currency, so Settings shows it and does not change it.

## Declare a section

In the part's own `<app>/preferences.py` (imported at startup):

```python
from pydantic import Field

from karni import preferences


@preferences.section("bookings", title="Bookings", change="role:bookings-manager")
class BookingPreferences(preferences.Section):
    """How bookings are refunded."""

    refund_notice_hours: int = Field(
        0,
        ge=0,
        le=720,
        description="A paid booking cancelled at least this many hours before the "
        "slot starts is refunded. 0 refunds every cancelled paid booking.",
    )
```

| Argument | Meaning |
|---|---|
| key | The part's prefix (`bookings`). `details`, `connections` and `emails` are reserved. |
| `title` | The tab's title on the Settings page. |
| `change` | Who else may change it: a permission key (`bookings.resource:change`) or `role:<slug>`. Holders of `preferences.sectionvalue:change` (`admin`, through `"*"`) change every section. |
| `describe` | One line under the title (default: the first line of the docstring). |
| `version` | The shape of the stored values, from 1. Raise it when a field changes meaning. |

Every field needs a default (`E321` otherwise), so a project that never opens
Settings works. A field's `description` is its help line, and its constraints
(`ge`, `max_length`, a `Literal` of choices) are checked on every change. The
section is stored as the values someone changed, in JSON. A field removed from
the model is ignored, and a stored value the model now refuses gives way to
the default, with a warning in the log.

## Read a value

One call, with a typed default:

```python
from karni import preferences

hours = preferences.value("bookings.refund_notice_hours", 0)   # an int
name = preferences.value("details.name", "")                   # a str
section = preferences.get(BookingPreferences)                  # the whole section, typed
```

A value is, in this order: a test's `override`, the deployment's lock
(`KARNI_PREFERENCES_LOCKED`), what someone saved in Settings, the deployment's
default (`KARNI_PREFERENCES_DEFAULTS`), and the declared default. The answer
has the type of the default you pass: a stored `"12"` read with the default
`0` is `12`, and a value that cannot be read as that type is logged and the
default returned.

`value()` never fails because something is missing. Without the app, or
without the part that declares the section, it returns the lock or the
default you gave. So a part reads its settings the same way whether or not
the project installed preferences.

| Path | Answer |
|---|---|
| `details.<field>` | a detail: `name`, `legal_name`, `address`, `phone`, `email`, `tax_number`, `sender_name`, `sender_email`, `reply_to`, `time_zone`, `language`, `currency`, `currency_display`, `logo` (its address) |
| `<section>.<field>` | a field of a section |
| `connections.<name>` | whether the connection is active |
| `emails.<kind>` | whether the email goes out |

`preferences.details()` gives every detail at once, and `preferences.sender()`
the `From` of the project's emails (`"Harbour Yoga <hello@harbour.example>"`,
or `None` to keep `DEFAULT_FROM_EMAIL`). A blank time zone reads as
`TIME_ZONE`, a blank language as `LANGUAGE_CODE`, a blank sender name as the
business's name.

Inside a request, each table is read once and kept until a change is saved,
so reading ten values costs one query per table.

## Connections

A connection is something one part does because another thing is installed.
It is code on one side, written against a contract or a module, never against
another part. Declare it in the part's `<app>/connections.py`:

```python
from karni import preferences

preferences.connection(
    "crm.deal_timeline",
    needs=["timeline"],
    default=True,
    describe="A won or lost deal is written on the deal's timeline.",
)
```

and ask before doing the work:

```python
if preferences.active("crm.deal_timeline"):
    timeline.record(kind="crm.deal.won", title=f"Deal won: {deal.title}", subjects=[deal])
```

`active()` is true when the connection is declared, everything in `needs` is
installed and its switch is on. `needs` names core contracts (`people`,
`events`, `timeline`, `preferences`) and modules by app label
(`karni_payments`). A connection switches itself on when what it needs is
installed, and Settings, Connections can switch it off. Connections keep
their declared default when `karni.preferences` is not installed.

Test each connection twice: on, and switched off with `preferences.override`
(below).

## Emails

Settings, Emails lists every email the project sends, each with a switch:

- the emails of a move (`moves.<state>.notify` in karni.yaml,
  [rules](rules.md#moves)), named `<app>.<model>_<state>`
  (`bookings.booking_confirmed`), without a declaration,
- emails a part declares: `preferences.email("crm.quote_sent", title="Quote
  sent", describe="...")`,
- the messages a part declares in its `messages.py` with
  `karni.mail.register_kind(...)` (the order confirmation, the parcel
  shipped), with who gets them. One declared `switchable=False` (a sign-in
  code) always goes out: its switch is fixed, and switching it off is refused
  (`E323`).

`preferences.email_on(kind)` answers whether an email goes out. A move's
email checks it, and comes from the details' sender. So does every message
`karni.mail` sends: its source reads the switches and the sender from here
while `karni.preferences` is installed. A message with merge fields shows an
Edit button on the Settings page while [notifications](notify.md)
(`karni.notify`) are installed: they keep the emails a business rewrote, over
`/api/email-templates/`, and each person's own switches.

## Locks and deployment defaults

```python
# config/settings.py
KARNI_PREFERENCES_LOCKED = {
    "details": {"currency": "EUR"},
    "bookings": {"refund_notice_hours": 48},
    "connections": {"crm.deal_timeline": False},
    "emails": {"bookings.booking_cancelled": True},
}
KARNI_PREFERENCES_DEFAULTS = {"details": {"name": "Harbour Yoga"}}
```

A locked value is what every read answers, the Settings page lists it under
`locked` and shows it read only, and changing it is refused with `E324`
(409). A deployment default is where a value starts: the business can change
it. `karni check` refuses a lock or a default that names a section, field,
connection or email nobody declared, or a value its field refuses (`E320`).

## The Settings API

| Request | Answer |
|---|---|
| `GET /api/preferences/` | The page: `details` (values, fields, locked), `sections` (each with its JSON schema, values, defaults, locked fields), `connections` (each with `needs`, `installed`, `on`, `active`, `locked`), `emails` (the sender and each kind's switch). Each part says `can_change` for the caller. 403 for a caller who may change nothing. |
| `PATCH /api/preferences/details/` | Some details, as JSON, or multipart with a `logo` file. A blank value goes back to the default, `"logo": null` removes the logo. |
| `PATCH /api/preferences/sections/<key>/` | Some fields of a section. `null` puts a field back to its default. |
| `PATCH /api/preferences/connections/<name>/` | `{"on": true}`, `{"on": false}` or `{"on": null}` (the default again). |
| `PATCH /api/preferences/emails/<kind>/` | The same, for an email. |
| `GET /api/preferences/history/` | The latest 100 changes: table, record, action, the fields that moved, who. |
| `GET /api/preferences/public/` | The details anyone may see (name, legal name, address, phone, contact email, tax number, logo, time zone, language, currency, currency display), for the header, the footer and money formatting. No sign-in. |

Who may change what: `preferences.details:change` for the details,
`preferences.switch:change` for connections and emails, and each section's
`change`. `admin` holds them through `"*"`. A refused change answers 400
`E323` with `errors` per field, 409 `E324` for a locked value, or 404 `E325`
for a name nobody declared.

## The admin

Details (one row, never deleted), Section values (checked against their
section's model) and Switches. A locked detail is read only. Each row has its
History.

## Tests

```python
from karni import preferences

def test_without_the_timeline_connection(deal):
    with preferences.override(connections={"crm.deal_timeline": False}):
        ...
```

`preferences.override(**groups)` sets values for a block, over locks and
saved values: `details`, a section key, `connections` or `emails`.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `KARNI_PREFERENCES_LOCKED` | `{}` | Values the deployment fixes, by group then name. |
| `KARNI_PREFERENCES_DEFAULTS` | `{}` | Values the deployment starts with, by group then name. |
| `KARNI_PREFERENCES_API` | `True` | Mount `/api/preferences/`. |
| `KARNI_PREFERENCES_AUTODISCOVER` | `True` | Import every app's `preferences.py` and `connections.py` at startup. |

## Escape hatches

- `preferences.unregister(section="bookings")` and a section of the project's
  own under the same key, or `replace=True` on `section()` and `connection()`.
- `build_urlpatterns(force=True)` from `karni.preferences.api` mounts the
  views in a URLconf of your own, and each view can be subclassed.
- The models are plain Django models: read them in reports, export them.

## What it does not do

- It does not hold secrets. API keys and passwords stay in the environment.
- It does not hold per-user choices (a user's language, which emails a
  person wants). Those belong to the person and to
  [notifications](notify.md).
- It does not render the Settings page. The page, with one tab per part and
  the Emails and Connections tabs, is built on this API in @karni/ui.
- karni-site keeps its own settings row for now. Reading the name, address
  and phone from the details when both are installed is planned.

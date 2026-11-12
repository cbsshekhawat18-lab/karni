---
description: "The people contract in Karni (experimental): one Person per human and one Organisation per company for every part of a project, found or created by email with people.resolve, linked to an account once its email is verified, with person facts in SQL, duplicates, merge with a preview and hooks, erase on request, an API, an admin and a shared seed pool."
---

# People

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `karni.people` app and its models (`Person`, `Organisation`,
    `Membership`, `Address`), the functions of `karni.people`
    (`resolve`, `link_account`, `register_fact` and its builders,
    `duplicates`, `merge_plan`, `merge`, `merge_hook`, `erase`, `erase_hook`,
    `erasable`, `pool`), the events of `karni.people.events`, the
    `KARNI_PEOPLE*` settings, the people endpoints and `fk:people.Person` in
    `karni.yaml`. The contract carries a version, `karni.people.CONTRACT`
    (now `1`). It becomes stable once the six recipes use it; after that a
    breaking change warns for one minor release first. The error codes keep
    their meaning.

A project that holds several parts (a shop, a CRM, bookings, courses) meets
the same human in each of them: a buyer, a contact, a guest, a student. The
people contract keeps one record of that human, a `Person`, and one record of
each company, an `Organisation`, and every part points at them. One email is
one person in every part.

A person may have a user account or none. The account is how someone signs
in. The person is who they are: a guest buyer, a lead from a web form and an
imported contact are people without an account.

## Turn it on

```python
# config/settings.py, above karni_settings(globals())
KARNI_PEOPLE = True
```

`karni_settings()` then adds `karni.people` (app label `people`) to
`INSTALLED_APPS`, before `karni.admin`. Run `migrate`. A spec does it for
you: a relation to a contract model turns the contract on, and `karni build`
writes `KARNI_PEOPLE = True` in the settings block.

```yaml
apps:
  club:
    entities:
      Visit:
        fields:
          person: fk:people.Person
          company: "fk:people.Organisation?"
      Card:
        fields: {holder: o2o:people.Person}
```

The targets are `people.Person`, `people.Organisation`, `people.Membership`
and `people.Address` (`C230` for another name). An app of the spec that is
itself named `people` stays the spec's own.

## The records

| Model | Fields |
|---|---|
| `Person` | `given_name`, `family_name`, `display_name`, `email`, `phone`, `organisation` (the main one), `user` (one to one, may be empty), `time_zone`, `language`, `source` (the part that created it), `merged_into`, `erased_at` |
| `Organisation` | `name`, `domain`, `phone`, `source`, `merged_into` |
| `Membership` | `person`, `organisation`, `title` |
| `Address` | `person` or `organisation` (one of them), `label`, `line1`, `line2`, `city`, `region`, `postcode`, `country` (ISO 3166), `is_default_billing`, `is_default_shipping` |

Every model is a `BaseModel`: UUID keys, timestamps, soft delete and change
history. The rules they keep:

- `email` is stored lower case and is unique among live people when it is
  not blank. A second person with the same email is a 400 `E254` in the API
  and the admin.
- A person linked to an account has the account's email. Changing it on the
  person is `E255`: change it through the account.
- `display_name` follows the given and family names (or the email) until
  someone writes it by hand.
- `time_zone` is an IANA name and `language` a language tag (`E256`).
- An address belongs to exactly one owner (a CHECK in the database, `E256`).
  Each owner has at most one default billing and one default shipping
  address: saving a default clears the owner's other one.
- A person is a member of an organisation once.
- Deleting a person clears its account link, so the account can be linked
  again.

A part never adds a column to these tables. It keeps its own table that
points at a person: a profile one to one with `Person` (a CRM's contact
profile), or rows with a foreign key (orders, bookings, enrolments).

## Find or create a person: `people.resolve`

```python
from karni import people

person = people.resolve(email=form["email"], name=form["name"], source="crm")
buyer = people.resolve(user=request.user, source="shop")
```

`resolve` is the one call a part makes when it meets someone. With a `user`,
the person linked to that account wins; otherwise the live person with the
email (the account's email when no `email` is given). When none exists, it
creates one, unless `create=False`, which returns `None`. It fills the
person's blank names and phone from what it is given and never overwrites a
known value. Without a user and without an email it raises `E253`: a name
alone does not identify anyone. On PostgreSQL the row is locked for the rest
of the transaction, so two checkouts with one email do not race.

The escape hatch is `KARNI_PEOPLE_RESOLVER`: the dotted path of a subclass of
`karni.people.Resolver` that overrides `find`, `create`, `fill` or `link`.

## The account link

An account is linked to a person only once its email is verified, so nobody
takes over a guest's orders by signing up with their address. Every flow that
proves an address sets the account's `email_verified`: the verification link,
a sign-in with an email code, a social sign-in with a verified address. When
that happens, the live person with the account's email gets the account, and
`people.person.linked` is published. Nothing else is created: a person is
made when a part meets the account (`resolve(user=...)`) or when it opens its
own page (`/api/people/me/`).

`people.link_account(user)` does the same by hand, and refuses (`E258`) an
account whose email is not verified, a person with another email, or a
person that has another account. `KARNI_PEOPLE_LINK_ON_VERIFY = False` leaves
linking to the parts.

## What parts contribute: `<app>/people.py`

Each installed app's `people.py` is imported at startup. A part declares its
person facts, merge hooks and erase hooks there:

```python
# helpdesk/people.py
from django.db.models import Q

from karni import people

from helpdesk.models import SupportProfile, Ticket

people.register_fact(
    "open_tickets", people.count_of(Ticket, filter=Q(status="open")), label="Open tickets"
)


@people.merge_hook(SupportProfile)
def merge_profiles(keep, drop):
    kept = SupportProfile.objects.filter(person=keep).first()
    dropped = SupportProfile.objects.filter(person=drop).first()
    if kept and dropped:
        kept.plan = max(kept.plan, dropped.plan)
        kept.save()
        dropped.delete()


people.erasable(Ticket, fields={"contact_name": "", "contact_email": ""})
```

`KARNI_PEOPLE_AUTODISCOVER = False` stops the import; the same calls then go
in the part's `AppConfig.ready()`.

### Person facts

A fact is one SQL expression about a person, contributed by a part: how many
orders, the total spent, the next booking. The CRM's segments, the person page
and a shop's customers list read them without knowing which part contributed
them:

```python
from karni.people.models import Person

Person.objects.with_facts("orders", "total_spent").filter(total_spent__gte=100)
```

The builders make correlated subqueries, so two parts' facts in one query
count right and a list costs one query whatever the number of facts:

| Builder | Value |
|---|---|
| `people.count_of(Model, path="person", filter=Q(...))` | the number of live rows |
| `people.sum_of(Model, "amount", path="person", filter=...)` | the sum, 0 when there is none |
| `people.latest_of(Model, "starts_at", path="person", filter=...)` | the latest value, or `None` |
| `people.exists_of(Model, path="person", filter=...)` | whether there is a row |

`register_fact(name, expression, label=, kind=, description=)` takes any
expression (or a function that returns one) and `@people.fact(name)`
decorates such a function. `kind` is one of `count`, `number`, `money`,
`date`, `datetime`, `boolean`, `text`, for screens that format the value. A
fact's name is an identifier that is not a field of `Person`; a taken name,
an unknown kind or an unknown fact is `E257`. `replace=True` swaps a fact on
purpose, `people.unregister_fact(name)` removes one and `people.facts()`
lists them.

## Duplicates

Email is the identity, so two live people never share one.
`people.duplicates()` finds what an email check misses, as groups of people:

| Rule | Finds |
|---|---|
| `email_tag` | the same email apart from a `+tag` (`ana+shop@example.com`, `ana@example.com`) |
| `name_without_email` | the same full name where at least one of them has no email |

`duplicates(people=queryset, rules=[...], person=p)` narrows the people, the
rules and the groups. A part adds its own rules (a CRM's phone, name with
organisation and domain) with `people.register_duplicate_rule(name, find)`,
where `find(queryset)` returns lists of person keys.

## Merge

```python
plan = people.merge_plan(keep, drop)   # the preview: plan.moves, plan.fills, plan.refusals
people.merge(keep, drop)               # does it, or raises MergeRefused (HTTP 409)
```

`keep` and `drop` are two people or two organisations. In one transaction,
with both rows locked, a merge:

1. runs the merge hook of each model that has one;
2. moves to `keep` every row that still points at `drop`: every foreign key
   and one-to-one to the model in every installed app, found through the
   models' meta (soft-deleted rows too), and every `GenericForeignKey` that
   points at it (a note on any record);
3. fills `keep`'s blank fields from `drop` (names, phone, organisation, time
   zone, language, email, and the account when `keep` has none);
4. sets `drop.merged_into` and soft-deletes `drop`;
5. records every moved row in one audit `ChangeBatch` of kind `people.merge`
   (`{field: [drop, keep]}` per row), with both records' own changes;
6. publishes `people.person.merged` or `people.organisation.merged`.

A merge is refused, with nothing changed, when:

| Code | Why |
|---|---|
| `E250` | both people have an account: merge the accounts first, by hand |
| `E251` | both records have a one-to-one row of a model without a merge hook, or moving rows breaks a unique rule of their model; the message names the model |
| `E252` | the two records are the same, deleted or merged already, or not of one kind |

Karni's own hooks keep one membership per organisation (the title is kept)
and the kept record's default addresses. `KARNI_PEOPLE_MERGE_SKIP` lists
models (`"app_label.Model"`) a merge leaves alone. The change history of a
model is never moved: it stays with the record it describes.

## Erase

```python
people.erase(person)
```

For a person's request to delete their data. In one transaction every
registered erase hook runs first (each part anonymises its own rows: an order
keeps its amounts and loses the name), then the person's addresses are
blanked and deleted, its memberships deleted, and the person keeps its key
and loses every detail: names, email, phone, organisation, time zone,
language and the account link. It is marked `erased_at`, soft-deleted, and
shows as "Erased person". The change history of the person and its addresses
keeps no value: each value becomes `[erased]`. The rows are written with
`QuerySet.update()`, so no listener sees the old values. The user account is
not deleted: that is the accounts' own flow. Erasing twice does nothing.
`people.person.erased` is published.

`people.erasable(Model, fields={...}, path="person")` registers the common
hook: write those values on the person's rows of the model and redact them
from the rows' history. `@people.erase_hook(name)` registers any function
`hook(person)`, and `people.redact_history(Model, ids, fields=[...])` is
what such a hook uses for the history.

## Events

Published from `karni.people.events`, inside the transaction of the change:

| Event | When | Declared fields |
|---|---|---|
| `people.person.created` | any part creates a person | `source` |
| `people.person.linked` | an account is linked after a verified email | `user` |
| `people.person.merged` | two people became one | `kept`, `removed` |
| `people.person.erased` | a person's data was erased | |
| `people.organisation.created` | any part creates an organisation | `source` |
| `people.organisation.merged` | two organisations became one | `kept`, `removed` |

Each is a Django signal (`person_created`, `person_linked`, `person_merged`,
`person_erased`, `organisation_created`, `organisation_merged`). A receiver
gets `payload`, which holds ids and values only (`id`, `name`, `version`,
`occurred_at`, `actor`, `person`, `subject` as `{"model", "id"}`,
`request_id` and the declared fields), and `subject`, the row itself. A
receiver runs inside the publisher's transaction, so raising undoes the
change. Publishing an event that is not declared, or with other fields, is
`E259`.

## The API

| Endpoint | What |
|---|---|
| `/api/people/` | people: list, detail, create, change, delete |
| `/api/organisations/` | organisations |
| `/api/people-memberships/` | memberships |
| `/api/people-addresses/` | addresses |
| `GET, PATCH /api/people/me/` | the signed-in user's own person: names, phone, time zone, language |
| `GET /api/people/facts/` | the registered facts: name, label, kind, source |
| `GET /api/people/{id}/merge-plan/?drop=<id>` | the merge preview |
| `POST /api/people/{id}/merge/ {"drop": "<id>"}` | the merge (409 with the plan when refused) |
| `GET /api/people/duplicates/?rule=` | the groups of possible duplicates |
| `POST /api/people/{id}/erase/` | erase (204) |
| `GET /api/organisations/{id}/merge-plan/`, `POST .../merge/` | the same for organisations |

Every endpoint answers the roles granted on it (`Granted()`). A grant with
scope `own` reaches the person linked to the user (`Person`'s owner field is
`user`), and their memberships and addresses. `merge` and `erase` are
explicit actions: only a grant that names them reaches them, so `"*"` does
not. Grant them by name, for example
`{"*": "all", "people.*:merge": "all", "people.person:erase": "all"}`. `me` is
open to every signed-in user. Nothing stamps `user` on a create: an account is
linked only through a verified email.

On the people list, `?facts=orders,total_spent` (or `facts=all`) adds a
`facts` object to each row, `?orders__gte=3` filters on a fact (`gt`, `gte`,
`lt`, `lte`, `isnull`, or nothing for equals) and `?ordering=-total_spent`
orders on one, in SQL: the list costs the same number of queries for 10 rows
or 10,000.

A part shows person data inside its own records through its own access
rules, so a CRM's "own, team, all" holds for its users whatever they may do on
`/api/people/`. `KARNI_PEOPLE_API = False` leaves these endpoints out, for a
project that routes its own viewsets over the people tables.

## Search, admin and seeds

`Person` (display name, email, phone) and `Organisation` (name, domain)
declare [cross-model search](global-search.md), so `GET /api/search/` finds
them for whoever may list them, and a customer finds only themself.

The admin lists people and organisations with their memberships and
addresses inline. *Merge the selected two* shows the plan, lets you choose
which row stays and merges on confirmation; *Erase the selected people's
data* asks first. Both need the explicit permission.

`karni seed` makes one shared pool of organisations and people, before any
part's rows: invented names, emails at example domains (members of an
organisation on its own domain), a home address for every other person, and
an account for a third of them (password `karni-password`). The demo login
is the first person of the pool. A part's seeders pick people from the pool
in a fixed order, so the same person is the shop's customer, the CRM's
contact and the guest of next week's class:

```python
buyers = people.pool()                      # or pool(with_account=True)
person = buyers[index % len(buyers)]
```

## Settings

| Setting | Default | What |
|---|---|---|
| `KARNI_PEOPLE` | `False` | installs `karni.people` (read during the `karni_settings()` call) |
| `KARNI_PEOPLE_RESOLVER` | `"karni.people.services.Resolver"` | the class `resolve` uses |
| `KARNI_PEOPLE_LINK_ON_VERIFY` | `True` | link an account when its email is verified |
| `KARNI_PEOPLE_API` | `True` | route the people endpoints |
| `KARNI_PEOPLE_MERGE_SKIP` | `[]` | models a merge leaves alone |
| `KARNI_PEOPLE_AUTODISCOVER` | `True` | import each app's `people.py` |

## What it does not do

- It does not merge user accounts: two people with an account are refused.
- It does not delete a user account when it erases a person.
- It does not find duplicates by phone, company or domain on its own: a part
  registers those rules.
- It holds no part's fields: a part keeps a profile table of its own.

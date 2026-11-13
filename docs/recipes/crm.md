---
description: "The CRM recipe: companies, contacts, deals in a pipeline and activities, with sales (crm-rep), manager (crm-manager) and admin roles and import and export on companies and contacts. What it builds and changes."
---

# Recipe: CRM

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

Companies, their contacts, the deals a sales team works through a pipeline,
and the calls, emails and meetings on each deal. A salesperson sees their
own deals, a manager sees every deal, and an admin sees everything.

```sh
karni new "Acme Sales" --recipe crm
```

## Entities and roles

The app `crm`:

| Entity | Fields | Owner | Who reads, who writes |
|---|---|---|---|
| Company | name (the import key), website, industry, phone, notes | | the roles' grants |
| Contact | company, first_name, last_name, email (`email:unique`, the import key), phone, title | | the roles' grants |
| Deal | company, contact, title, value (`money`, in `app.currency`), salesperson, stage (`state`), expected_close | salesperson | the roles' grants |
| Activity | deal, salesperson, kind (`choice:call\|email\|meeting\|note`), due_at, done, notes | salesperson | the roles' grants |

A deal's stage moves `lead > qualified > proposal > won`, and to `lost`
from `lead`, `qualified` or `proposal`. Companies, contacts and deals keep
their change history (`audit: true`).

| Role | Grants |
|---|---|
| `admin` | a system role: everything |
| `crm-manager` | named Manager: `crm.*: all`, every company, contact, deal and activity |
| `crm-rep` | named Sales: `all` on companies and contacts, `own` on deals and activities |

No role is given at sign-up (`default: false` on both): an admin gives each
account its role.

Every list exports as CSV or XLSX and imports from a file with a preview
([import and export](../import-export.md)). The `key` of Company (`name`)
and Contact (`email`) makes a row of an import an update of the row with
that name or email.

## Rules

Declared in `karni.yaml` ([rules](../rules.md)), so a rebuild keeps them:

- A company's name is unique, and a company or contact with deals, or a deal
  with activities, is not deleted (`E991`, `E995`).
- A deal's contact works at the deal's company (`E993`), its value is not
  negative and an open deal does not close in the past (`E990`). A new deal
  starts as a lead (`E982`).
- Marking a deal lost needs a reason (`lost_reason`, `E996`); won and lost
  stamp `closed_at`. A won deal keeps its value and company (`E994`).
- Only a manager or admin deletes a deal or gives it to another salesperson
  (`E135`); a salesperson marks it lost. An activity marked done stamps
  `done_at`.

## Modules and settings

- `two_factor`: people can protect their sign-in with an authenticator
  app (`karni[2fa]`).
- `preferences` (core, required): Settings, CRM has `stale_after_days` (30): an open deal nobody changed for that long is listed by `GET /api/deals/stale/`. Managers and admins change it. The connection `crm.deal_timeline` (on) writes a won or lost deal on the deal's and its company's [timeline](../timeline.md) when the project has one, and Settings, Connections switches it off.

Pages: the staff dashboard, and under the app's route `/crm`: companies,
contacts and deals (list, detail, form) and activities (list, form). Demo data: 20 companies, 60 contacts, 40
deals and 120 activities.

## Domain code

- `crm/viewsets.py`: `GET /api/deals/pipeline/` answers the number and the
  value of the deals per stage, of the deals the user may see.
- `crm/tests/test_pipeline.py`: the pipeline as sales and as a manager, and
  a contacts import that updates by email.
- `crm/preferences.py`, `crm/connections.py` and `crm/listeners.py`: the settings section, the connection and the timeline entries it writes. `crm/tests/test_family.py` tests the stale deals, who may change the setting, and the timeline with the connection on and off.
- `crm/seeds.py`: twenty companies in different trades, three contacts at
  each with an email on the company's own `.example` domain, two deals each
  that fit the trade, a contact from the same company on every deal, and
  calls, emails and meetings that are done when their date has passed. The
  companies come from `COMPANIES`.
- `crm/tests/test_seeds.py`: the demo data is the same for one seed, has the
  counts of `karni.yaml`, and its people and deals agree with their company.

## What people usually change

| Change | In karni.yaml |
|---|---|
| the pipeline stages | `apps.crm.entities.Deal.fields.stage`, for example `"state:new>contacted>demo>won\|new>lost\|contacted>lost\|demo>lost"` |
| the company and contact fields | `fields` of `Company` and `Contact` |
| what sales and managers may see | `roles.crm-rep.grants` and `roles.crm-manager.grants`, for example `crm.company: own` with `owner` on Company |
| the currency of a deal's value | `app.currency: EUR` |

Then run `karni build`.

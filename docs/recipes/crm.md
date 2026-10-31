---
description: "The CRM recipe: companies, contacts, deals in a pipeline and activities, with sales, manager and admin roles and import and export on companies and contacts. What it builds and changes."
---

# Recipe: CRM

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

Companies, their contacts, the deals a sales team works through a pipeline,
and the calls, emails and meetings on each deal. A salesperson sees their
own deals, a manager sees every deal, and an admin sees everything.

```sh
karni new "Northwind Sales" --recipe crm
```

## Entities and roles

The app `crm`:

| Entity | Fields | Owner | Who reads, who writes |
|---|---|---|---|
| Company | name (the import key), website, industry, phone, notes | | the roles' grants |
| Contact | company, first_name, last_name, email (`email:unique`, the import key), phone, title | | the roles' grants |
| Deal | company, contact, title, value (`money:USD`), salesperson, stage (`state`), expected_close | salesperson | the roles' grants |
| Activity | deal, salesperson, kind (`choice:call\|email\|meeting\|note`), due_at, done, notes | salesperson | the roles' grants |

A deal's stage moves `lead > qualified > proposal > won`, and to `lost`
from `lead`, `qualified` or `proposal`. Companies, contacts and deals keep
their change history (`audit: true`).

| Role | Grants |
|---|---|
| `admin` | a system role: everything |
| `manager` | `crm.*: all`, every company, contact, deal and activity |
| `sales` | `all` on companies and contacts, `own` on deals and activities |

No role is given at sign-up (`default: false` on both): an admin gives each
account its role.

Every list exports as CSV or XLSX and imports from a file with a preview
([import and export](../import-export.md)). The `key` of Company (`name`)
and Contact (`email`) makes a row of an import an update of the row with
that name or email.

## Modules and settings

- `two_factor`: people can protect their sign-in with an authenticator
  app (`karni[2fa]`).

Pages: the staff dashboard, companies, contacts and deals (list, detail,
form) and activities (list, form). Demo data: 20 companies, 60 contacts, 40
deals and 120 activities.

## Domain code

- `crm/viewsets.py`: `GET /api/deals/pipeline/` answers the number and the
  value of the deals per stage, of the deals the user may see.
- `crm/tests/test_pipeline.py`: the pipeline as sales and as a manager, and
  a contacts import that updates by email.

## What people usually change

| Change | In karni.yaml |
|---|---|
| the pipeline stages | `apps.crm.entities.Deal.fields.stage`, for example `"state:new>contacted>demo>won\|new>lost\|contacted>lost\|demo>lost"` |
| the company and contact fields | `fields` of `Company` and `Contact` |
| what sales and managers may see | `roles.sales.grants` and `roles.manager.grants`, for example `crm.company: own` with `owner` on Company |
| the currency of a deal's value | `money:EUR` on `Deal.fields.value` |

Then run `karni build`.

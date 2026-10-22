---
description: karni.fields - typed model fields (money, percent, quantity, email, slug, phone, country, currency, JSON, search, arrays) whose rules the database enforces, uniqueness that respects soft delete, the checks that catch float money and cascading deletes, and karni schema.
---

# Typed fields

An agent writing a model reaches for `FloatField` for money, a free-text
`CharField` for a country and a case-sensitive unique email. None of that
fails a test, but all of it fails in production. `karni.fields` makes the correct
column, constraint and index the default: you declare what a value **is**,
and the database enforces it, so raw SQL, bulk updates, imports and other
services writing the table cannot get around it.

```python
from django.db import models
from karni.fields import (
    CountryField, EmailField, MoneyField, PercentField, QuantityField, SearchField, SlugField,
)
from karni.models import BaseModel

class Product(BaseModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    slug = SlugField(populate_from="name")          # unique among live rows, generated
    price = MoneyField(currency="EUR", min_value=0)  # NUMERIC(19,4), Decimal only
    discount = PercentField(default=0)              # CHECK 0..100
    stock = QuantityField(default=0)                # CHECK (stock >= 0)
    made_in = CountryField(blank=True)              # CHECK IN ISO 3166-1 alpha-2
    search = SearchField(sources=["name", "description"])  # generated tsvector + GIN

class Customer(BaseModel):
    email = EmailField(unique=True)                 # unique on LOWER(email), live rows
```

`karni make model` writes them from the field DSL:
`karni make model Product name:str:200 slug:slug:name price:money:EUR stock:quantity made_in:country?`.

## The field set

Every field is the plain Django field plus what the database must
guarantee. "Backends" says what holds where. PostgreSQL gets everything.
SQLite (tests, local development) gets the portable part, and system check
`karni.W964` says what is missing there. `karni.E964` stops a field that
cannot work at all.

| Field | Column | Constraint | Index | Backends | Plain Django replacement |
|---|---|---|---|---|---|
| `MoneyField(currency=` or `currency_field=)` | `NUMERIC(19,4)` | `CHECK` from `min_value`/`max_value` | - | exact on PostgreSQL, while SQLite stores NUMERIC as a binary float (W964) | `models.DecimalField(max_digits=19, decimal_places=4)` |
| `PercentField(min_value=0, max_value=100)` | `NUMERIC(p,2)` | `CHECK` between the bounds | - | all | `DecimalField` + `CheckConstraint` |
| `QuantityField` | `integer` | `CHECK (col >= 0)` | - | all | `models.PositiveIntegerField` |
| `EmailField(unique=True)` | `varchar(254)` | unique on `LOWER(email)` (partial on soft-deletable models) | the unique index | all | `models.EmailField` + `UniqueConstraint(Lower("email"))` |
| `SlugField(populate_from=...)` | `varchar(50)` | unique (partial on soft-deletable models) | the unique index | all | `models.SlugField(unique=True)` |
| `PhoneField` | `varchar(32)` | `CHECK` E.164 (regex on PostgreSQL, `GLOB` on SQLite) | - | PostgreSQL, SQLite (others: no CHECK, W964) | `models.CharField(max_length=32)` |
| `CountryField` | `varchar(2)` | `CHECK (col IN (...ISO 3166-1 alpha-2...))` | - | all | `models.CharField(max_length=2, choices=...)` |
| `CurrencyField` | `varchar(3)` | `CHECK (col IN (...ISO 4217...))` | - | all | `models.CharField(max_length=3, choices=...)` |
| `JSONField(queried=True)` | `jsonb` | - | GIN when `queried=True` | GIN on PostgreSQL only (W964) | `models.JSONField` + `GinIndex` |
| `SearchField(sources=[...])` | generated `tsvector` | - | GIN | PostgreSQL, and elsewhere a plain-text column and portable search (W964) | `GeneratedField(SearchVector(...))` + `GinIndex` |
| `ArrayField(base_field)` | `type[]` | - | GIN unless `indexed=False` | PostgreSQL only (E964 elsewhere) | `django.contrib.postgres.fields.ArrayField` |

Every field accepts all of its Django base field's arguments (`null`,
`blank`, `default`, `db_column`, `help_text`, `db_comment`, ...), and every
one can be replaced by the plain field in the last column. Migrations
reference them as `karni.fields.<Name>`, so a module move inside Karni never
breaks a migration.

### MoneyField

- **A currency is required**, exactly one of: `currency="EUR"` (one fixed ISO
  4217 code for the column) or `currency_field="currency"` (a `CurrencyField`
  on the same model holds each row's currency). Neither, both, or a code that
  is not ISO 4217 raises `karni.E961` when the model is defined.
  `field.currency_for(row)` returns the code.
- **Decimal only.** Assigning a float (`product.price = 9.99`), passing one to
  `create()`, a lookup or `update()` raises `karni.E962`: a binary float has
  lost the exact cent value before Karni sees it. Ints and `Decimal` are
  exact. Strings are parsed by Django as usual. Mixing a float into an `F()`
  expression is already refused by Django.
- **A declared rounding rule.** Values are quantized to `decimal_places` with
  `rounding=` (default `decimal.ROUND_HALF_EVEN`) before they reach the
  database, so the stored value never depends on the database's own rounding
  (PostgreSQL rounds half away from zero).
- **Arithmetic helpers**: `quantize(value, places, rounding)`,
  `split(total, parts, places)` and `allocate(total, ratios, places)`. An
  allocation always sums to the total exactly (largest remainder):
  `split(Decimal("100"), 3)` is `[33.34, 33.33, 33.33]`.

### PercentField and QuantityField

`PercentField` takes `min_value`/`max_value` (0 and 100 by default) and
derives `max_digits` from them. `decimal_places` defaults to 2. The bounds
are a column CHECK and validators, so forms and the API reject them too.
`QuantityField` is a `PositiveIntegerField`: a decrement that would take
stock below zero fails at the database even when two requests race.

### EmailField

`unique=True` is case-insensitive: the constraint is a unique index on
`LOWER(email)`, so `Alice@x.com` and `alice@x.com` cannot both exist, not even
through raw SQL. The domain is lower-cased on save and in lookups
(`filter(email="Alice@EXAMPLE.com")` finds `Alice@example.com`). The local
part keeps its case. Django 5 removed the `CI*` fields and Karni does not
need `citext`. The generated serializer checks the same rule with `iexact`,
so a duplicate is a 400, not a database error.

### SlugField

Unique by default (`unique=False` to opt out). With `populate_from="name"` an
empty slug is generated on save. A value a live row holds gets `-2`, `-3`,
... and, after 50 tries, a random suffix. The unique constraint still rejects
a duplicate from a concurrent insert. A number as the DSL argument
(`code:slug:40`) is a `max_length`, as before.

### PhoneField

Stored in E.164: `+`, country code and number, at most 15 digits
(`+14155552671`). Input may carry spaces, dashes, dots, parentheses, a
`(0)` trunk marker or a `00` prefix (`"+44 (0)20 7946 0958"` is stored as
`+442079460958`). A national number without a country code is rejected, not
guessed. There is no dependency: per-country number plans need Google's
`phonenumbers` (megabytes of metadata). Add `validators=[...]` built on it
when well formed is not enough and you must know a number is assignable.

### CountryField and CurrencyField

Both carry the ISO list as `choices` (so the admin, forms and the OpenAPI
enum get it) and as a database CHECK. `codes=[...]` narrows to a subset,
`extra_codes=[...]` widens it (`"XK"`). The lists ship with Karni
(`karni.fields.iso_data`: 249 country codes, and ISO 4217 list one with 179
codes, including fund and metal codes). The CHECK is a named constraint that lists
the codes: when a Karni release updates a list, `makemigrations` replaces it,
and each field records the list's `iso_revision`.

### JSONField, SearchField, ArrayField

- `JSONField(queried=True)` adds a GIN index for `meta__contains={...}` and
  `meta__has_key=...`. Leave it off for a document that is only read whole:
  a GIN index costs on every write.
- `SearchField(sources=["title", "description"], config="simple",
  weights={"title": "A"})` is a stored generated column: the database
  recomputes it on every write, raw SQL included, so it never drifts. It is
  never in the API, factories or the change history. List it in a viewset's
  `search_fields` (or list exactly its sources) and the default search
  provider matches through its GIN index: every word is a prefix
  (`walnu` finds `walnut`), all words must match, rows rank by `ts_rank`.
  The trigram leg is not combined with it, because `similarity() > t` cannot
  use an index. A source the requester may not read (`APIMeta.write_only`,
  `Karni.field_roles`) turns it back into a search of the readable sources.
- `ArrayField(models.CharField(max_length=40))` adds a GIN index for
  `contains`/`overlap`/`contained_by`. It needs a PostgreSQL driver to import
  and PostgreSQL to migrate. Use `JSONField` for a portable list.

## Uniqueness that respects soft delete

A soft-deleted row stays in its table, so a plain unique index keeps its
value reserved forever: a deleted user's email can never sign up again, a
deleted event's slug can never be reused. Two ways to declare uniqueness over
live rows (`WHERE deleted_at IS NULL`, a partial unique index PostgreSQL and
SQLite both enforce):

- `unique=True` on any Karni field. On a `SoftDeleteModel` it becomes a
  `LiveUniqueConstraint`, and elsewhere a plain `UniqueConstraint`. The column
  itself never carries `UNIQUE`, so `field.unique` is `False`. Use
  `karni.fields.is_unique(field)` instead.
- `LiveUniqueConstraint` for anything else, including several fields:

  ```python
  class Seat(BaseModel):
      venue = models.ForeignKey(Venue, on_delete=models.PROTECT)
      label = models.CharField(max_length=10)

      class Meta(BaseModel.Meta):
          constraints = [LiveUniqueConstraint(fields=["venue", "label"])]
  ```

  `name` is optional (derived from the table and fields), `condition=` is
  combined with the live-row condition. On a model without soft delete it is
  `karni.E968`. The generated serializers validate it, so a live duplicate is
  a 400. A database without partial indexes (MySQL) does not create it:
  `karni.W964`.

## Checks

| Code | Level | Catches | Escape hatch |
|---|---|---|---|
| `karni.E960` | error | a `FloatField` named like money (price, amount, total, cost, fee, subtotal, tax, balance, ...) | `class Karni: not_money = {"field": "<what it is>"}` |
| `karni.E961` | error | a `MoneyField` without a valid currency, or whose `currency_field` is not a `CurrencyField` | - |
| `karni.E963` | error | a declaration that cannot work: `populate_from` or a `SearchField` source that is not a field, reversed bounds, an unknown ISO code or rounding mode | - |
| `karni.E964` | error | a field the configured database cannot run (an `ArrayField` on SQLite) | another field, or PostgreSQL |
| `karni.W964` | warning | a PostgreSQL guarantee missing on the configured database (exact NUMERIC, GIN, tsvector, the E.164 CHECK, partial unique indexes) | `SILENCED_SYSTEM_CHECKS` |
| `karni.W965` | warning | `on_delete=CASCADE` on a financial model (a money field, a money-named decimal, a payments-like name, or `Karni.financial = True`) or an audited one (`Karni.audit`) | `class Karni: cascade = {"field": "<why>"}` |
| `karni.W967` | warning | a column a routed viewset searches, filters or orders by with no index | add the index, or `SILENCED_SYSTEM_CHECKS` for a small table |
| `karni.E968` | error | `LiveUniqueConstraint` on a model without soft delete | `models.UniqueConstraint` |
| `karni.E970` | error | a malformed `not_money`, `cascade` or `append_only` option | - |

Every CHECK a field implies (bounds, ISO lists, E.164) is a named
`CheckConstraint` the field adds to `Meta.constraints`, so it is in the
migration and reaches an existing column too: Django re-creates column-level
CHECKs on `ALTER` only for its own field types, which would leave a column
converted to a Karni field unchecked. `QuantityField` keeps Django's own
`>= 0` column CHECK.

NOT NULL is the database's job too: every field is `NOT NULL` unless you
pass `null=True`, whatever `blank` says.

## Indexes from declared usage

| Declared | Index | Who adds it |
|---|---|---|
| a foreign key | B-tree on `<fk>_id` | Django (`ForeignKey(db_index=True)`). Karni adds none |
| `SearchField` | GIN on the tsvector | the field |
| `JSONField(queried=True)` | GIN | the field |
| `ArrayField` | GIN | the field |
| `class Karni: append_only = True` | BRIN on the `auto_now_add` timestamps (or the listed columns), replacing their B-tree | the option |
| range fields | GiST | the range field, through `karni.fields.contribute_index` |
| `search_fields`, `filterset_fields`, `ordering_fields`, an `ordering` on a viewset | the index `karni.W967` names | you, from the message |

Indexes that follow from the model are added to its `Meta` when the class is
prepared, so `makemigrations` writes them like any other. Viewset usage is
checked rather than added: migrations come from the models, and a model must
not change shape depending on which API modules happen to be imported.
`karni.W967` names the exact line, for example
`models.Index(fields=["status"], name="events_event_status_3c9f2a1b_idx")`,
or a `SearchField` for a searched column (a B-tree cannot serve `?search=`).
A column is covered by a primary key, a unique column or constraint, a
`db_index`, a foreign key's index, or any index whose first column it is.

BRIN (`append_only`) is a few kilobytes instead of a B-tree the size of the
column, for tables that only grow and are read by time range. It cannot serve
`ORDER BY created_at LIMIT n`, so do not declare it on a table listed
newest first.

`GinIndex`, `GistIndex` and `BrinIndex` from `karni.fields` are the
`django.contrib.postgres` indexes with one difference: on another database
creating them is a commented no-op instead of a syntax error, so one
migration runs everywhere.

## karni schema

`karni schema [app | app.Model ...] [--json] [--no-db]` lists, per model,
every column with its type and the declaration behind it, every constraint
and index with its SQL and why it exists, and, when the table exists,
whether the database has it (`[ok]`, `[MISSING]`: run `karni migrate`,
`[skipped]`: a PostgreSQL index on another database). It also lists the
columns routed viewsets use, with what serves each, and database objects no
declaration explains (a `RunSQL` index, a leftover). `--json` gives agents
the same data.

```text
fieldsapp.Customer  (table fieldsapp_customer, postgresql)
  columns
    id          uuid                      not null  UUIDField primary key (from UUIDModel)
    deleted_at  timestamp with time zone  null      DateTimeField (from SoftDeleteModel)
    email       varchar(254)              not null  EmailField: varchar(254), domain lower-cased on save
  constraints and indexes
    [ok] index fieldsapp_customer_created_by_id_f924f9c8
        INDEX (created_by_id)
        why: ForeignKey created_by: Django indexes every foreign key (db_index=True), so Karni adds none
    [ok] constraint fieldsapp_customer_email_51eea71f_uniq
        CREATE UNIQUE INDEX "fieldsapp_customer_email_51eea71f_uniq" ON "fieldsapp_customer" ((LOWER("email"))) WHERE "deleted_at" IS NULL
        why: EmailField(unique=True): unique, lower-cased, among live rows (WHERE deleted_at IS NULL): a soft-deleted row's value can be reused
```

`karni.fields.schema.describe(model)` builds the same report in code.

## Extensions

Karni creates the PostgreSQL extensions it relies on by migration, in every
project: `pg_trgm` (`karni.accounts` 0004, the search provider's trigram
leg) and `btree_gist` (`karni.accounts` 0005, plain columns inside GiST
exclusion constraints). Both are a no-op on other databases. In your own
migrations:

```python
from karni.fields import CreateExtension

class Migration(migrations.Migration):
    operations = [CreateExtension("unaccent")]
```

`CreateExtension` checks `pg_extension` first, so a role without the right to
create extensions migrates fine once a DBA created them, and never drops one
on rollback. When the database refuses, it raises `karni.E966` with the exact
SQL:

- as a superuser, in the project's database:
  `CREATE EXTENSION IF NOT EXISTS btree_gist;`
- or, for a **trusted** extension on PostgreSQL 13 and later (`pg_trgm`,
  `btree_gist`, `citext`, `unaccent`, ...), let the role create it itself:
  `GRANT CREATE ON DATABASE "shop" TO "shop_app";`. The database owner already
  holds that right. An untrusted extension always needs a superuser.

## The model DSL

| Syntax | Generates |
|---|---|
| `price:money:EUR` | `MoneyField(currency="EUR")` |
| `price:money` | `price_currency = CurrencyField()` and `MoneyField(currency_field="price_currency")` |
| `rate:percent[:min:max]` | `PercentField(default=0)`, bounds optional |
| `stock:quantity` | `QuantityField(default=0)` |
| `email:email[:unique]` | `EmailField()`, `unique=True` with `:unique` |
| `slug:slug[:source]` | `SlugField(populate_from="source")` (a number is a `max_length`) |
| `phone:phone`, `country:country`, `currency:currency` | `PhoneField()`, `CountryField()`, `CurrencyField()` |
| `meta:json[:queried]` | `JSONField(default=dict)`, `queried=True` with `:queried` |
| `tags:array:str[:len]` | `ArrayField(models.CharField(max_length=len))` (base types: str, text, int, bool, date, datetime, uuid) |

A trailing `?` makes any of them optional. A bad argument is `C360`.

## Escape hatches

- Replace any field with its plain Django field (the table above): the
  column type stays, and the constraint goes unless you declare it.
- `unique=False` drops the unique constraint, `queried=False` / `indexed=False`
  drop a GIN index, and `codes=`/`extra_codes=` change an ISO list.
- Subclass a field and override `karni_constraints(model)` or
  `karni_indexes(model)` to change what it contributes.
  `karni.fields.contribute_index(model, index, why)` adds an index (with its
  reason) from your own field type.
- Opt-outs that need a reason: `Karni.not_money`, `Karni.cascade`.
- Silence a warning project-wide with `SILENCED_SYSTEM_CHECKS`.

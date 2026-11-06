---
description: "Karni's recipes: ready-made karni.yaml files for a shop, bookings, a CRM, online courses, a marketplace and a data portal. karni new --recipe builds one with its domain code, demo data and tests."
---

# Recipes

!!! warning "Experimental"
    The built-in recipes, `karni new --recipe`, the `recipe` key of
    `.karni/build.json` and `karni_cli.recipes.apply` are
    [experimental](../stability.md#experimental-names). They may change in a
    minor release, and each change is in the CHANGELOG. The error codes keep
    their meaning.

A recipe is a good starting spec for a kind of app many people ask for, plus
the little domain code a spec cannot express. The spec is a
[`karni.yaml`](../app-spec.md), so Karni turns it into code without a
language model, and the domain code is a few methods, actions, seeders and
tests in the files the project owns. Each recipe also switches on the
modules and features that suit it, so a recipe doubles as a profile.

```sh
karni new "Corner Shop" --recipe shop
```

| Recipe | For | Entities | Modules and features | Domain code |
|---|---|---|---|---|
| [`shop`](shop.md) | an online shop | Category, Product, Cart, CartItem, Order, OrderItem | payments, email code login, terms | 84 lines: the order total, checkout |
| [`booking`](booking.md) | booking a slot of a resource | Resource, Slot, Booking | payments, email code login | 66 lines: a slot never takes more bookings than its capacity |
| [`crm`](crm.md) | a sales team's deals | Company, Contact, Deal, Activity | two-factor sign-in | 15 lines: the pipeline per stage |
| [`lms`](lms.md) | online courses | Course, Lesson, Enrolment, LessonProgress | email code login | 52 lines: a student's completion of a course |
| [`marketplace`](marketplace.md) | sellers and buyers | Seller, Listing, Order, Payout | payments, two-factor sign-in, terms | 58 lines: the payout after the fee |
| [`data-portal`](data-portal.md) | datasets and indicators by region and sector | Region, Sector, Dataset, Indicator | saved charts, per-user grants, response caching | 139 lines: the trees, datasets, indicators and the saved chart of the demo data |

The domain code counts the lines beyond what `karni build` writes in the
same files anyway. Each recipe also ships tests of its own rules.

`karni recipes list --match "<the request>"` picks the recipe for a one-line
request (an online shop, book a class, track sales deals, online courses, a
marketplace for sellers, a data portal), and `karni recipes show <name>` prints its spec,
its files and what people usually change. Where they come from, the
`recipe.toml` format and recipes of your own are in [the app
spec](../app-spec.md#recipes).

## What `karni new --recipe` does

1. It renders the project as `karni new` does. The kind is the recipe's
   (`app`), or `--kind site+app` for a public site next to the app.
2. It writes the recipe's `karni.yaml` with the project's name as
   `app.name`, the kind as `app.kind` and the recipe as `app.recipe`.
3. It names the recipe in `.karni/build.json` (`"recipe": "shop"`): the
   first `karni build` that writes puts the recipe's own files in.
4. It runs `karni build` in the new project. The build adds the modules,
   writes Karni's code and its stubs for the project's files, then the
   recipe's own files over those stubs, then runs the migrations, seeds
   the demo data with the recipe's seeders, runs the project's tests (the
   recipe's among them) and `karni check`.

Without an interpreter that has Django and karni for the project (its
`.venv`, the active virtualenv, or the one running karni-cli), or without
a database it can open, it stops after step 3 and says the one command
left: `karni build`. That build does step 4 the same way.

The output for the shop, from an empty folder:

```text
Created ./corner_shop: kind app (recorded under [tool.karni] in pyproject.toml), ...
Recipe shop (Online shop): wrote karni.yaml (app.recipe: shop) and named the recipe in .karni/build.json. The first karni build writes its own files over its stubs: shop/models.py, shop/seeds.py, shop/tests/test_checkout.py, shop/viewsets.py.

$ karni build
...
40 changes, 0 risky.
modules     karni add payments
files       30 written: 21 Karni's, 9 the project's (pyproject.toml, shop/__init__.py, ...)
migrations  shop/migrations/0001_initial.py
migrate     applied 81 on default
seed        Cart 10, Category 5, Order 30, Product 40, CartItem 30, OrderItem 80 (demo login demo@example.com / karni-password)
types       frontend/src/api/types.ts and hooks.ts
test        15 passed in 8.84s, tests/openapi.snapshot.json updated (the API changed: commit it)
check       ok
Built: the project matches karni.yaml.
```

`karni new "<Name>" --recipe blank` writes the blank start (the version and
the app's name) and builds nothing. An unknown recipe is refused with
[C420](../errors.md#c420), which names the closest recipes, and `--design`,
`--kind site` or `--no-staff-app` with a recipe with
[C440](../errors.md#c440). Nothing is written then.

## How fast is it

Karni times what a person waits for in CI, so the speed cannot slip unnoticed.
`scripts/benchmark/speed.py` runs on every push. These are the times it
measured on a developer Mac (Apple silicon, the median of 3 runs, SQLite, no
frontend install, a machine with other work on it, so they are a little high):

| Step | Seconds |
| --- | --- |
| `karni new --recipe lms`, from scratch to a built project | 11.0 |
| `karni new --recipe data-portal` | 12.0 |
| `karni new --recipe crm` | 12.4 |
| `karni new --recipe booking` | 12.6 |
| `karni new --recipe marketplace` | 12.9 |
| `karni new --recipe shop` | 13.5 |
| the `/new-app` flow with a scripted agent, request to green `karni check` | 14.1 |
| `karni build` again, no spec change | 1.4 |
| `karni check`, cold (no cache) | 3.8 |
| `karni check`, cached | 2.0 |
| `karni spec validate` | 0.37 |
| `karni plan` | 1.4 |
| `karni plan --questions` | 0.38 |

Inside a recipe build the time goes to the project's own tests (3 to 4
seconds), the migrations and the demo data (about 1.5 seconds each), the types
(1 to 1.5 seconds) and `karni check` (about 2 seconds). `karni plan` and
`karni check` take as long as they do because each starts the project's Django once.

Each time has a budget: the baseline (`scripts/benchmark/speed-baseline.json`)
times how much slower or faster the machine is than the one that recorded it
(the same calibration as the large-project benchmark), times 1.5, plus a few
seconds of slack. A build with no spec change has its own ceiling of 5 seconds
on any machine. The `speed` job fails when a step goes over, and keeps the times
as an artifact. Run it yourself with `python scripts/benchmark/speed.py`, and
record a new baseline on a quiet machine with `--record` when a growth is
expected.

## The stub rule

`karni build` creates the project's own files (`<app>/models.py`,
`viewsets.py`, `seeds.py`) as stubs: a docstring, an import and a class per
entity that extends Karni's. A recipe's file replaces such a file only
while it is still exactly that, and creates a file the project does not
have (its own tests). A file with code of the project's in it stops the
build with [C441](../errors.md#c441), naming each file, and nothing is
written. A recipe's file never goes where Karni writes its own code
(`<app>/karni/`, `<app>/tests/karni/`, the `karni:spec` blocks): such a
recipe cannot be used ([C421](../errors.md#c421)).

When karni.yaml has an entity the recipe does not (added before the first
build), build's stub class for it stays, after the recipe's code.

## After the first build

The recipe's files are the project's from then on. `karni build` never
writes them again and only adds a class for a new entity, as it does for
any project file. Change the app in `karni.yaml` (each recipe's page says
how for what people usually change), then run `karni build`. The recipe's
domain code is written for its entities and fields: after a rename, move
the methods that name the old one.

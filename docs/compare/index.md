---
description: How Karni compares with cookiecutter-django, SaaS Pegasus, plain Django + DRF and Django React boilerplates, including where each alternative is the better choice.
---

# Comparisons

Each page says what Karni and the alternative both do, where each is the
better choice, and who should pick which. Every page includes the rows where
Karni loses: it is version 0.3, released in October 2026, with no known
production deployment and no community yet. Facts about other projects were
checked on 2026-10-21 and link to their sources.

- [Karni vs cookiecutter-django](cookiecutter-django.md): a generated Django
  project you own, against a framework you upgrade.
- [Karni vs SaaS Pegasus](saas-pegasus.md): a commercial SaaS boilerplate with
  billing and teams, against an open-source framework without them.
- [Karni vs plain Django + DRF](django-drf.md): the standard stack, against
  the same stack with the per-model layers derived.
- [Karni vs a Django React boilerplate](django-react-boilerplate.md): a
  template copied once, against a dependency that keeps receiving fixes.

## In one table

| | Plain Django + DRF | cookiecutter-django | SaaS Pegasus | React boilerplate | Karni |
|---|---|---|---|---|---|
| You start with | an empty project | a generated project you own | a generated codebase you own (paid, with an open-source edition) | a copied repository | a dependency you upgrade |
| Per-model API, admin, permissions | you write them | you write them | generated once, then yours | you write them | derived from the model and `access` rule |
| An upstream fix reaches your code | for Django and DRF | no official path | regenerate and merge | no | `karni upgrade` |
| React front end | your own | not offered | HTMX or React | yes | `@karni/ui` |
| Subscriptions, teams, multi-tenancy | no | no | yes | some (Apptension) | no |
| Maturity | decades | since 2013 | since 2019 | since 2016 / 2020 | since October 2026 |
| AI agent guidance in the project | none | none in the generated project | rule files, skills, MCP | not checked | instruction files for eight tools, MCP, lint rules |

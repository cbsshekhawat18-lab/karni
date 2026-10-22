---
description: Karni, an open-source framework you upgrade, compared with SaaS Pegasus, a commercial Django SaaS boilerplate. Includes where Karni loses.
---

# Karni vs SaaS Pegasus

SaaS Pegasus is a commercial Django boilerplate: it generates a codebase with
the technologies and SaaS features you choose, and you own and extend that
code. Karni is an open-source framework you install and upgrade: a project
declares models and access rules, and the API, admin, permissions and React
screens are derived from them. Facts about SaaS Pegasus were checked against
its website and documentation on 2026-10-21 ([sources](#sources)).

## What both do

Both start a Django project with authentication, a REST API documented with
drf-spectacular, Celery, Docker and a modern front-end build. Both ship
guidance for AI coding agents (rule files and agent instructions) and both
have a documented way to bring a new release into an existing project.

## Where SaaS Pegasus is the better choice

- **SaaS features.** Pegasus ships Stripe subscriptions, teams and
  multi-tenancy, AI chat and agents, one-click deploys and Wagtail. Karni has
  a payments module (Stripe and Razorpay checkout) but no subscriptions, teams
  or multi-tenancy.
- **Maturity and support.** Pegasus has been sold since 2019, states that 1,910
  developers and businesses use it, releases about monthly and offers email
  and Slack support. Karni's first release was in October 2026, with no known
  production deployment and no commercial support.
- **Front-end choice.** Pegasus offers HTMX or React (and a Vue example) with
  several CSS frameworks. Karni supports React only.
- **Newer Django.** Pegasus's open-source edition targets Django 6 on Python
  3.14, while Karni 0.4 supports Django 5.2 LTS on Python 3.12 to 3.14.

## Where Karni is the better choice

- **Licence and price.** Karni is free and Apache-2.0 licensed. Pegasus's paid
  tiers are a one-time $449 (one project) or $649 (unlimited projects), each
  with one year of updates, under a licence that does not allow redistributing
  the code (an MIT-licensed open-source edition covers a smaller feature set).
- **How upgrades work.** Pegasus upgrades by regenerating code into your
  repository and merging it with git, resolving conflicts by hand. Karni keeps
  the generic code in versioned packages, and `karni upgrade` applies code
  changes with codemods and lists what it could not change
  ([stability promise](../stability.md)).
- **Per-model code.** In a Pegasus project the generated code is yours to
  maintain. In Karni a resource is its model and its `access` rule, and the
  serializer, viewset, admin, permissions and React screens are derived from
  them ([the API](../api.md)).
- **Agent enforcement.** Beyond rule files, Karni's lint rules and
  `karni check` fail a build when an agent hand-writes a table, form or HTTP
  call that Karni provides ([enforcement](../enforcement.md)).

## Who should pick which

Pick SaaS Pegasus to launch a subscription SaaS soon, with billing, teams and
support included, and a team happy to own the generated code. Pick Karni for
an internal tool, line-of-business application or product where most screens
are permissioned CRUD, where the team wants the generic code kept upstream,
and where a young, unsupported framework is an acceptable risk.

## Side by side

| | SaaS Pegasus | Karni |
|---|---|---|
| What you get | a generated codebase you own | a dependency you upgrade, plus a scaffold |
| Price and licence | $449 / $649 one-time (1 year of updates), or the MIT open-source edition | free, Apache-2.0 |
| In market since | 2019, 1,910 customers stated | October 2026 |
| Subscriptions, teams, multi-tenancy | yes | no (payments module only) |
| Front end | HTMX or React (Vue example) | React only |
| Upgrading | regenerate and merge with git | `karni upgrade` with codemods |
| Per-model API, admin, permissions | generated once, then yours | derived from the model and `access` rule |
| AI agent support | rule files, CLAUDE.md / AGENTS.md, skills, MCP | instruction files for eight tools, MCP server, build-failing lint rules |
| Support | email, Slack (paid tiers) | GitHub issues |
| Django version | 6 (open-source edition) | 5.2 LTS |

## Sources

- SaaS Pegasus home page and pricing: <https://www.saaspegasus.com/>,
  <https://www.saaspegasus.com/pricing/> (as of 2026-10-21)
- Licence: <https://www.saaspegasus.com/license/>
- Upgrading: <https://docs.saaspegasus.com/upgrading/>
- Documentation summary: <https://docs.saaspegasus.com/llms.txt>
- Open-source edition: <https://github.com/saaspegasus/django-boilerplate>
- Karni: the [README](https://github.com/cbsshekhawat18-lab/karni#readme),
  [the API](../api.md), [stability promise](../stability.md),
  [enforcement](../enforcement.md)

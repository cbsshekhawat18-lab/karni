---
description: A Django React boilerplate template such as Vinta's or Apptension's is copied once, and Karni is upgraded. This page compares them and says who should pick which.
---

# Karni vs a Django React boilerplate template

A Django React boilerplate is a repository you copy to start a project: the
code becomes yours and evolves separately from the template. Two of the most
used are vintasoftware/django-react-boilerplate (Django, DRF, React and
TypeScript) and apptension/saas-boilerplate (Django with GraphQL, React and
SaaS features). Karni is a framework you install and upgrade instead of
copying. Facts were checked on 2026-10-21 ([sources](#sources)).

## What both do

Both give a new project a Django back end, a React and TypeScript front end,
a typed API client or schema, Celery, Tailwind and a Docker setup, so a team
starts from working defaults instead of an empty repository.

## Where a boilerplate is the better choice

- **Maturity.** Vinta's boilerplate dates from 2016 with around 2,300 GitHub
  stars and 55 contributors, and Apptension's from 2020 with around 3,000
  stars. Both are backed by companies that offer commercial services. Karni's
  first release was in October 2026.
- **SaaS features.** Apptension's boilerplate includes Stripe subscriptions,
  multi-tenancy with roles, passkeys and two-factor sign-in. Karni has no
  subscriptions or multi-tenancy.
- **Ownership.** Every line of a boilerplate is the project's to change, with
  no framework dependency. A Karni project depends on the `karni` package and
  follows its conventions.
- **Recognition.** Vinta's boilerplate is listed in awesome-django. Karni is
  not yet eligible for such lists.

## Where Karni is the better choice

- **Updates reach existing projects.** A boilerplate is copied once, and fixes
  made to the template later do not reach projects created from it, and neither
  boilerplate documents a way to pull them in. Karni upgrades like any
  dependency, and `karni upgrade` applies code changes with codemods
  ([stability promise](../stability.md)).
- **Per-model code.** A boilerplate shows how to write the serializer, view,
  permissions and screens for a model. Karni derives them from the model and
  its `access` rule ([the API](../api.md)).
- **AI coding agents.** Karni projects ship agent instruction files, an MCP
  server and lint rules that stop an agent from re-creating framework code in
  each project ([agents](../agents.md)).

## Who should pick which

Pick a boilerplate when the team wants a proven starting point to own and
reshape freely, or needs the SaaS features one already includes. Pick Karni
when the application has many permissioned CRUD resources, the team wants
framework fixes to keep reaching the project, and a young framework is an
acceptable risk.

## Side by side

| | Django React boilerplate | Karni |
|---|---|---|
| How you start | copy the repository | install packages, `karni new` |
| Later template fixes | do not reach your project | `karni upgrade` with codemods |
| Per-model API, admin, permissions | written per model, following the template's examples | derived from the model and its `access` rule |
| Maturity | since 2016 (Vinta), 2020 (Apptension) | October 2026 |
| SaaS features | Apptension: subscriptions, multi-tenancy, 2FA | payments module only |
| API style | DRF (Vinta), GraphQL (Apptension) | DRF with an OpenAPI schema |
| Framework dependency | none | the `karni` package |

## Sources

- <https://github.com/vintasoftware/django-react-boilerplate>
- <https://github.com/apptension/saas-boilerplate>
- awesome-django: <https://github.com/wsvincent/awesome-django>
- Karni: [the API](../api.md), [stability promise](../stability.md),
  [agents](../agents.md)

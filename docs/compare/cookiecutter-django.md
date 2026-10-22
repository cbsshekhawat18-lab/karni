---
description: Karni compared with cookiecutter-django — what each generates, how each is kept up to date, and who should pick which. Includes where Karni loses.
---

# Karni vs cookiecutter-django

cookiecutter-django generates a complete, production-oriented Django project
that you then own. Karni is a framework you install and upgrade: a project
declares models and access rules, and the API, admin, permissions and React
screens are derived from them. Facts about cookiecutter-django were checked
against its repository and documentation on 2026-10-21 ([sources](#sources)).

## What both do

Both start a new Django project in one command with a custom user model,
user accounts, Celery, PostgreSQL in Docker, environment-based
settings and tests. Both target teams that want sensible defaults instead of
assembling a project by hand.

## Where cookiecutter-django is the better choice

- **Maturity.** cookiecutter-django has been developed since 2013 by about 480
  contributors, has around 13,600 GitHub stars and releases almost daily;
  Karni's first release was in October 2026 and it has no known production
  deployment.
- **Deployment breadth.** cookiecutter-django documents Docker with Traefik and
  Let's Encrypt, Heroku and PythonAnywhere, with options for AWS, GCP and
  Azure storage and four CI providers; Karni generates a Docker Compose stack
  that has not yet been tested end to end.
- **No runtime dependency.** The generated project is plain Django, so nothing
  ties it to cookiecutter-django after generation; a Karni project depends on
  the `karni` package at runtime.
- **Newer Django.** cookiecutter-django targets Django 6.0; Karni 0.3 supports
  Django 5.2 LTS only.
- **Community.** cookiecutter-django has a Discord server, a Stack Overflow tag
  and a listing in awesome-django; Karni has none of these yet.

## Where Karni is the better choice

- **A React front end.** cookiecutter-django's maintainers have said they do
  not intend to add React; Karni ships `@karni/ui`, React components that read
  the API's OpenAPI schema to render tables, forms and detail views.
- **Per-model code.** cookiecutter-django leaves serializers, viewsets,
  permission classes, filters and admin classes to be written per model; Karni
  derives them from the model and its `access` rule ([the API](../api.md)).
- **Upgrades.** cookiecutter-django has no official way to bring template
  changes into an existing project (its maintainers point to cruft or Copier);
  Karni upgrades like any dependency, and `karni upgrade` applies code changes
  with codemods ([stability promise](../stability.md)).
- **AI coding agents.** A generated cookiecutter-django project has no
  AGENTS.md or CLAUDE.md; a Karni project ships instruction files for eight
  agent tools from one rule set, an MCP server and lint rules that fail when
  an agent hand-writes what Karni provides ([agents](../agents.md)).

## Who should pick which

Pick cookiecutter-django for a server-rendered or HTMX Django project, for
deployment options that are proven in production, or when the team wants to
own every line with no framework dependency. Pick Karni for a Django REST API
with a React front end where most resources are CRUD with permissions, where
the team wants the generic code kept upstream and upgraded, and where a young
framework is an acceptable risk.

## Side by side

| | cookiecutter-django | Karni |
|---|---|---|
| What you get | a generated project you own | a dependency you upgrade, plus a scaffold |
| First release / maturity | 2013, about 480 contributors | October 2026, version 0.3 |
| Django version | 6.0 | 5.2 LTS |
| React front end | not offered | `@karni/ui`, schema-driven |
| REST API | optional DRF or Django Ninja, written per model | DRF, derived from each model and its `access` rule |
| Admin per model | written by hand | derived (django-unfold) |
| Row-level permissions | written by hand | declared once per resource |
| Upgrading an existing project | no official path (cruft or Copier) | `karni upgrade` with codemods |
| Deployment | Docker + Traefik, Heroku, PythonAnywhere, cloud storage options | Docker Compose, not yet tested end to end |
| AI agent files in the project | none | AGENTS.md, CLAUDE.md and six more, MCP server |
| Community | Discord, Stack Overflow tag, awesome-django | none yet |
| Licence | BSD-3-Clause | Apache-2.0 |

## Sources

- cookiecutter-django repository and README:
  <https://github.com/cookiecutter/cookiecutter-django> (stars, contributors,
  releases and features as of 2026-10-21)
- Generation options:
  <https://cookiecutter-django.readthedocs.io/en/latest/1-getting-started/project-generation-options.html>
- React support declined:
  <https://github.com/cookiecutter/cookiecutter-django/issues/4802>
- Updating generated projects:
  <https://github.com/cookiecutter/cookiecutter-django/issues/1047>
- Karni: the [README](https://github.com/cbsshekhawat18-lab/karni#readme),
  [the API](../api.md), [stability promise](../stability.md),
  [agents](../agents.md)

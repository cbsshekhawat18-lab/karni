---
description: How much you write per model with Karni and with plain Django, Django REST Framework and a React app, and when the plain stack is the better choice.
---

# Karni vs plain Django + Django REST Framework

Plain Django with Django REST Framework (DRF) and a separate React app is the
standard way to build a Django API with a React front end. Karni is built on
the same pieces (Django, DRF, django-filter and drf-spectacular) and
derives the per-model code from each model and its access rule. Facts about
the plain stack were checked on 2026-10-21 ([sources](#sources)).

## What both do

Both are Django and DRF underneath: models, viewsets, routers, filtering,
pagination, an OpenAPI schema and a React app talking to a JSON API. Anything
DRF can do, a Karni project can do, because a Karni viewset is a DRF viewset
and an explicit serializer or view is always allowed.

## Where plain Django + DRF is the better choice

- **Maturity and ecosystem.** Django has around 91,000 GitHub stars and DRF,
  first released in 2011, around 30,000 and 1,500 contributors. Stack Overflow
  has over 300,000 Django questions and over 31,000 DRF questions. Karni is
  new and has no community yet.
- **Flexibility.** Every package is chosen and replaceable, and nothing sits
  between the project and Django. Karni adds conventions (UUID keys, a base
  model, an `access` rule per resource) that a project accepts with it.
- **Versions.** DRF supports Django 5.2, 6.0 and 6.1, while Karni 0.4 supports
  Django 5.2 LTS only.
- **Long-term support.** Django's release and security policy is documented
  and proven over two decades. Karni is version 0.4 under a stability promise
  that has not yet been tested across a major release.

## Where Karni is the better choice

- **Code per model.** On the plain stack each model needs a serializer, a
  viewset, a router entry, permission classes, a filterset, an `admin.py`
  entry, a front-end data layer and tests. In Karni the model and an `access`
  rule produce them ([the API](../api.md), [testing](../testing.md)). Karni's
  reference application, with ticketing, payments, a Celery email and four
  roles, is 619 lines of project code ([tutorial](../tutorial.md)).
- **Row-level permissions.** One `access` rule is compiled into both the
  request check and the queryset filter, and a row outside the user's scope is
  a 404 on every endpoint, filter, export and expansion
  ([permissions at the queryset](../concepts/queryset-permissions.md)).
- **React screens.** react-admin and Refine are the usual CRUD front ends, but
  react-admin's only DRF data provider is a third-party package last updated in
  2023 and Refine lists no Django provider. Karni's `@karni/ui` reads the API's
  OpenAPI schema directly.
- **AI coding agents.** A Karni project ships agent instruction files, an MCP
  server and lint rules that stop an agent from hand-writing what the
  framework provides ([agents](../agents.md)).

## Who should pick which

Pick plain Django and DRF for a project whose API is mostly custom endpoints
rather than CRUD, for full control over every dependency, or where a young
framework is not an acceptable risk. Pick Karni when most of the API is
permissioned CRUD with a React admin-style front end, and the team would
rather declare models and access rules than write the same layers per model.

## Side by side

| | Django + DRF + React | Karni |
|---|---|---|
| Maturity | Django since 2005, DRF since 2011 | first release October 2026 |
| Per model you write | serializer, viewset, router, permissions, filterset, admin, front-end data layer, tests | the model and an `access` rule |
| Row-level permissions | permission classes plus `get_queryset`, per viewset | one `access` rule, enforced as 404 everywhere |
| React CRUD screens | react-admin or Refine (no maintained DRF provider) | `@karni/ui`, schema-driven |
| Django versions | 5.2, 6.0, 6.1 (DRF) | 5.2 LTS |
| Community | very large | none yet |
| Lock-in | none | the `karni` package at runtime |

## Sources

- Django: <https://github.com/django/django>, <https://pypi.org/project/Django/>
- Django REST Framework: <https://github.com/encode/django-rest-framework>,
  <https://www.django-rest-framework.org/api-guide/viewsets/>
- django-filter with DRF:
  <https://django-filter.readthedocs.io/en/stable/guide/rest_framework.html>
- react-admin data providers: <https://marmelab.com/react-admin/DataProviderList.html>
  and <https://github.com/bmihelac/ra-data-django-rest-framework>
- Refine data providers: <https://refine.dev/core/docs/data/data-provider/>
- Stack Overflow tag counts: <https://stackoverflow.com/tags> (as of 2026-10-21)
- Karni: [the API](../api.md), [testing](../testing.md),
  [tutorial](../tutorial.md), [agents](../agents.md)

---
description: Short, self-contained answers about Karni, the Django + React framework built to be extended by AI coding agents. They cover what it is, who it is for, and its limits.
faq: true
---

# Frequently asked questions

Each answer stands on its own, so it still makes sense quoted without the rest
of the page.

## What is Karni?

Karni is an open-source Django + React framework for building with AI coding agents. Your agent writes only your domain. The API, admin, permissions and React screens come from a package you upgrade, not code it rewrites in each project. One rule set covers every coding agent. The build fails when an agent hand-writes what Karni ships.

## How is Karni different from a Django boilerplate or starter template?

A Django boilerplate is copied into a project once, and its serializers,
permission classes and admin files then belong to that project to maintain.
Karni keeps that code in versioned packages (`karni` on PyPI, `@karni/ui` on
npm) and derives the per-model parts from each model and its `access` rule.
A Karni project moves to a new release with `karni upgrade`, which applies the
mechanical changes and lists the rest by file and line.

## Which AI coding tools does Karni work with?

Any coding agent that reads `AGENTS.md`. A new Karni project contains
`AGENTS.md`, generated from one rule set by `karni rules sync`, with the
procedures for routine tasks. `karni mcp` offers Karni's commands as MCP
tools, and `karni context` prints a compact summary of the project for an
agent. The [agents guide](agents.md) says what AGENTS.md carries.

## Does Karni work without AI coding tools?

Yes: nothing in Karni calls a language model. Every generator, such as
`karni make model`, is a command a person runs, and the
[guide for building without an agent](guide/without-ai.md) walks through the
same workflow by hand.

## How much code does a Karni project need per model?

A Karni resource needs the model, an `access` rule and whatever is specific to
the domain. The REST API, admin, permissions, React table and form, tests and
seed data come from the framework. In Karni's reference application, EventHub,
the `Venue` resource is a five-line model and a four-line viewset, and the
whole application (ticketing, payments, a Celery email, four roles) is 617
lines of project code, as measured in the [tutorial](tutorial.md).

## Is Karni production-ready?

Not yet. Karni 0.5.0 runs on Django 5.2 LTS and Python 3.12 to 3.14, with
two reference applications and CI on every push. CI
also boots a new project's production stack ([deploying to a server](deploy.md))
and smoke-tests it, but Karni has no known production deployment. Teams that
need a framework with years of production use should
weigh that before choosing Karni ([comparisons](compare/index.md)).

## What happens when Karni releases a breaking change?

A public name in Karni keeps working for at least one minor release and raises
a `KarniDeprecationWarning` that names the release that removes it.
`karni upgrade --to <version>` applies the mechanical changes with codemods
and lists, by file and line, what it could not change. The rules are in
Karni's [stability promise](stability.md).

## Can an existing Django project adopt Karni?

Not today: Karni scaffolds new projects with `karni new` and has no supported
path for converting an existing Django application. An existing project can
install the `karni` package and use parts of it, but that is undocumented and
outside Karni's stability promise. A team with an established codebase is
better served by its current stack until such a path exists.

## Which Python, Django and React versions does Karni support?

Karni 0.5.0 supports Python 3.12, 3.13 and 3.14, Django 5.2 LTS, Django REST
Framework and React 18 with TypeScript, and CI tests every Python version on
each push. Python 3.12 is the floor because Karni's admin is built on
django-unfold, whose current releases require Python 3.12.

The frontend needs Node 20.19 or later (22.12 or later on Node 22) and npm
10.8 or later, which those Node versions bundle. Node 24 LTS is recommended.
CI runs the quickstart page on Node 20, 22 and 24, each with the npm it
bundles.

## Why does `npm install` fail with "Cannot read properties of null (reading 'edgesOut')"?

npm before 11.6 crashes this way while it resolves optional peer dependencies
([npm/cli#8261](https://github.com/npm/cli/issues/8261), fixed in npm 11.6.0
and not in npm 10). Node 20 and 22 bundle npm 10. Vite 8 declares optional
peers that lead to vitest, whose own optional peers each pin one vitest
version. When those packages are out of step on the registry, an npm that
resolves them crashes, although none of them is ever installed.

A new project's `frontend/package-lock.json` pins every package but
`@karni/ui`, and npm installs what the lock pins without resolving Vite's
peers, so plain `npm install` works on npm 10. npm resolves them again when
`package-lock.json` is missing, on `npm update`, and when you add a package
that peers on Vite. The first install also resolves `@karni/ui` and the
optional peers its own peers declare, so a family among those that goes out
of step would crash npm 10 the same way. If one of those crashes, run the
same command once with npm 11.6 or later, for example `npx --yes npm@11
install`, or upgrade with `npm install -g npm@11`. Node 24 LTS bundles npm 11.
The lock that npm 11 writes then installs on npm 10 too. `karni doctor` shows
the Node and npm on your PATH and flags either one when it is too old.

## How does Karni handle permissions?

A Karni resource declares one `access` rule, such as `owned:organizer`, which
Karni compiles into both the request check and the row filter. A record
outside the user's scope returns 404 rather than 403, so its existence is not
revealed, and roles are data (`KARNI_ROLES`) checked with `user.can()`
([permissions at the queryset](concepts/queryset-permissions.md)).

## Is Karni free to use?

Yes. Karni is open source under the Apache License 2.0, and its packages are
published on PyPI and npm at no cost.

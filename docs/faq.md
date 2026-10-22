---
description: Short, self-contained answers about Karni, the Django + React framework built to be extended by AI coding agents — what it is, who it is for, and its limits.
faq: true
---

# Frequently asked questions

Each answer stands on its own, so it still makes sense quoted without the rest
of the page.

## What is Karni?

Karni is an open-source Django + React framework for building with AI coding agents. Your agent writes only your domain. The API, admin, permissions and React screens come from a package you upgrade, not code it rewrites in each project. One rule set covers Claude Code, Cursor and Copilot. The build fails when an agent hand-writes what Karni ships.

## How is Karni different from a Django boilerplate or starter template?

A Django boilerplate is copied into a project once, and its serializers,
permission classes and admin files then belong to that project to maintain.
Karni keeps that code in versioned packages (`karni` on PyPI, `@karni/ui` on
npm) and derives the per-model parts from each model and its `access` rule.
A Karni project moves to a new release with `karni upgrade`, which applies the
mechanical changes and lists the rest by file and line.

## Which AI coding tools does Karni work with?

A new Karni project contains the instruction files that Claude Code, Cursor,
GitHub Copilot, Windsurf, Cline, Aider, Junie and the tools that read
`AGENTS.md` (Codex, Gemini CLI, Zed and others) look for, all generated from
one rule set by `karni rules sync`. `karni mcp` offers Karni's commands as MCP
tools, and `karni context` prints a compact summary of the project for an
agent. The [agents guide](agents.md) lists every adapter and the file each
tool reads.

## Does Karni work without AI coding tools?

Yes: nothing in Karni calls a language model. Every generator, such as
`karni make model`, is a command a person runs, and the
[guide for building without an agent](guide/without-ai.md) walks through the
same workflow by hand.

## How much code does a Karni project need per model?

A Karni resource needs the model, an `access` rule and whatever is specific to
the domain; the REST API, admin, permissions, React table and form, tests and
seed data come from the framework. In Karni's reference application, EventHub,
the `Venue` resource is a five-line model and a four-line viewset, and the
whole application (ticketing, payments, a Celery email, four roles) is 608
lines of project code, as measured in the [tutorial](tutorial.md).

## Is Karni production-ready?

Not yet. Karni 0.3.1 was released on 2026-10-20 with Django 5.2 LTS and
Python 3.12 to 3.14, two reference applications and CI on every push, but it
has no known production deployment and its Docker setup has not been tested
end to end. Teams that need a framework with years of production use should
weigh that before choosing Karni ([comparisons](compare/index.md)).

## What happens when Karni releases a breaking change?

A public name in Karni keeps working for at least one minor release and raises
a `KarniDeprecationWarning` that names the release that removes it.
`karni upgrade --to <version>` applies the mechanical changes with codemods
and lists, by file and line, what it could not change; the rules are in
Karni's [stability promise](stability.md).

## Can an existing Django project adopt Karni?

Not today: Karni scaffolds new projects with `karni new` and has no supported
path for converting an existing Django application. An existing project can
install the `karni` package and use parts of it, but that is undocumented and
outside Karni's stability promise. A team with an established codebase is
better served by its current stack until such a path exists.

## Which Python, Django and React versions does Karni support?

Karni 0.3.1 supports Python 3.12, 3.13 and 3.14, Django 5.2 LTS, Django REST
Framework and React 18 with TypeScript; CI tests every Python version on each
push. Python 3.12 is the floor because Karni's admin is built on
django-unfold, whose current releases require Python 3.12.

## How does Karni handle permissions?

A Karni resource declares one `access` rule, such as `owned:organizer`, which
Karni compiles into both the request check and the row filter. A record
outside the user's scope returns 404 rather than 403, so its existence is not
revealed, and roles are data (`KARNI_ROLES`) checked with `user.can()`
([permissions at the queryset](concepts/queryset-permissions.md)).

## Is Karni free to use?

Yes. Karni is open source under the Apache License 2.0, and its packages are
published on PyPI and npm at no cost.

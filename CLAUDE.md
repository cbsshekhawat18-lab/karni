# Karni

Django + React framework that eliminates repeated boilerplate so AI coding agents write only domain-specific code.
Core principle: if code would be written more than once across projects, it belongs in a Karni
base class or component — never regenerated.

## Stack
- Python 3.12+, Django 5.2 LTS, DRF + drf-spectacular, Pydantic v2, django-environ
- PostgreSQL 16, Redis 7, Celery 5 (+ beat, + results)
- React 18, TypeScript strict, Vite, TanStack Query/Router/Table, Zustand, react-hook-form + Zod, Tailwind + Radix
- Docker Compose, GitHub Actions, Caddy
- ruff, mypy, pytest, factory-boy, ESLint, Prettier, Vitest, Playwright

## Repo layout
- `packages/karni/` — Python package (core)
- `packages/karni-ui/` — React component library (npm: @karni/ui)
- `packages/karni-cli/` — the `karni` command
- `templates/project/` — cookiecutter scaffold
- `modules/` — optional installable apps
- `docs/`

## Rules for all code in this repo
- Everything is a versioned dependency. The scaffold generates settings, urls, docker-compose and app code only. Never copy framework logic into templates.
- Every abstraction needs an escape hatch: overridable methods, swappable classes, settings-driven behaviour.
- No abstraction without three real occurrences of the pattern.
- Public API changes require a deprecation cycle: warn one minor, remove next major.
- Python: type hints everywhere, ruff for lint and format, pytest.
- TypeScript: strict mode, no `any`, vitest.
- Anything with meaningful RAM cost or a separate service belongs in `modules/`, not core.

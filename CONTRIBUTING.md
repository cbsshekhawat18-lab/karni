# Contributing to Karni

Thanks for helping. Karni exists so that projects write only domain code: if
something would be written more than once across projects, it belongs in a
Karni base class, component or command. Contributions are judged against that
idea first.

## Before you write code

- **Bugs:** open an issue with a minimal reproduction (the model, the
  viewset or `access` declaration, and the request or command that goes
  wrong).
- **Security problems:** do not open an issue. See [SECURITY.md](SECURITY.md).
- **"Karni should have provided this":** use the *Friction* issue template.
  Show the project code you had to write. These reports matter most: each one
  is a gap every Karni user hits.
- **New abstractions:** open an issue first. Karni adds an abstraction only
  when the pattern has **three real occurrences**, so link or paste them.

## Rules every change follows

These are the rules in [CLAUDE.md](CLAUDE.md). They bind humans and AI agents
alike.

1. **Everything is a versioned dependency.** The scaffold in
   `templates/project/` generates settings, urls, docker-compose and app code
   only. Framework logic never goes into a template, because a project could
   not upgrade it.
2. **Every abstraction has an escape hatch:** an overridable method, a
   swappable class, or a setting. Name the escape hatch in the docstring.
3. **No abstraction without three real occurrences of the pattern.**
4. **Public API changes need a deprecation cycle:** warn in one minor release,
   remove in the next major. See [docs/stability.md](docs/stability.md) for
   what counts as public API, and *Breaking changes* below for the mechanics.
5. **Anything with meaningful RAM cost or its own service goes in `modules/`**,
   not core.
6. **Python:** type hints everywhere, ruff for lint and format, pytest.
   **TypeScript:** strict mode, no `any`, vitest.

## Development setup

You need Python 3.12+ and Node 22.12+ (CI uses Node 24, and Vitest 5 needs 22.12 or later).

### Why Python 3.12 and not 3.11

This is a decision, checked on 2026-10-21 with a real CPython 3.11.17:

- **The admin requires it.** Karni's admin is built on django-unfold, pinned
  to 0.110. django-unfold has required Python 3.12 since 0.92.0. The last
  release that runs on 3.11 is 0.91.0, and it gets no fixes. Supporting 3.11
  would mean an admin pinned to an unmaintained release, or two admin versions
  to keep in step.
- **The code needs only small changes.** Four PEP 695 `type` aliases are a
  SyntaxError on 3.11: `karni/api/optimizer.py:72`, `karni/health/checks.py:24`
  and `:27`, and `karni/rows.py:19`. Each becomes `X: TypeAlias = ...`. With
  those changes and unfold 0.91 forced in, every package's suite passed on
  3.11. Nothing else needs 3.12: no other syntax, typing feature or stdlib
  call, and mypy at `--python-version 3.11` is clean. Every other dependency
  ships for 3.11.
- **3.11 would not cover Ubuntu 22.04 anyway.** Its system Python is 3.10.
  Debian 12's is 3.11.

On either system, get 3.12 from the scaffold's Docker image
(`python:3.12-slim`), `uv python install 3.12`, or the deadsnakes PPA on
Ubuntu. Revisit this if django-unfold supports 3.11 again or Karni's admin
moves off it. Lowering the floor then means changing `requires-python` in all
five packages, the ruff `target-version` (or UP040 rewrites the aliases back),
`mypy.ini`, the scaffold and module templates, and the CI matrix.

```sh
python3.12 -m venv .venv
make install PYTHON=.venv/bin/python   # editable installs + dev tools, npm ci per UI package
.venv/bin/pre-commit install                      # optional: lint on commit
.venv/bin/pre-commit install --hook-type pre-push # optional: mypy on push
```

Everything CI runs goes through the root Makefile, so local runs and CI cannot
drift:

```sh
make test      PYTHON=.venv/bin/python   # pytest per Python package, vitest per UI package
make lint      PYTHON=.venv/bin/python   # ruff check + format check, eslint + prettier
make typecheck PYTHON=.venv/bin/python   # mypy (root mypy.ini), tsc --noEmit
make format    PYTHON=.venv/bin/python   # fix formatting
```

`make install` also installs the three optional modules in `modules/`, and
`make test` tests them. A few tests in `packages/karni` and
`packages/karni-cli` check the modules' error codes and their documentation.
With only the core packages installed (`pip install -e packages/karni -e
packages/karni-cli`, or `make install-py test-py CORE_ONLY=1`), those tests
skip and name the module to install. CI runs both ways. Its full run sets
`KARNI_REQUIRE_MODULES=1`, so there a missing module fails instead of skipping.

`examples/eventhub` is the reference application, and CI builds, seeds and
tests it end to end. If your change breaks it, the change breaks Karni for
real users. Fix the framework, not the example.

## Repository layout

| Path | What it is |
|---|---|
| `packages/karni/` | The Python package: models, scopes, `access`, API, accounts, admin, events, schedule, testing, seeding |
| `packages/karni-ui/` | `@karni/ui`: React components, hooks and the ESLint plugin |
| `packages/karni-cli/` | The `karni` command: `new`, `make`, runners, `upgrade`, `context`, `rules` |
| `templates/project/` | The cookiecutter scaffold `karni new` renders |
| `modules/` | Optional installable apps (`karni add <module>`) |
| `docs/` | Documentation. Some pages are generated (see below) |
| `examples/eventhub/` | The reference application |
| `assets/brand/` | The Karni mark, wordmark and icons, with the usage rules in its README. `scripts/brand/` regenerates them |

## Generated files: regenerate, never hand-edit

Several files are generated from source, and a test fails when they go stale.
The failure message gives the exact command to regenerate them:

- `docs/cli.md`, generated from the CLI's own help:
  `python -m karni_cli.clidoc > docs/cli.md`
- the procedures block in `docs/agents.md`, generated from the rules registry
  in `karni/agent/rules.py`: paste the output of `karni rules --prompts-doc`
- the OpenAPI schema snapshot, `packages/karni/tests/api/fixtures/schema.testapp.json`,
  which the `@karni/ui` parser tests also use

## Breaking changes

A change that can break a project needs all of the following in the same pull
request:

1. **A changelog entry** in `packages/karni/karni/changelog/<next version>.toml`.
   The schema is in that package's `__init__.py`: what changed, which symbol,
   the replacement, and whether the change is mechanical or manual.
2. **A codemod** when the change is mechanical: one per change, named by
   version, under `packages/karni-cli/karni_cli/upgrades/v<major>_<minor>/`.
   It uses libcst for Python and jscodeshift for TypeScript, and has a test
   that runs it on a before/after fixture.
3. **A deprecation warning**, when the old name can keep working for a release.
   Use `karni.deprecation`. The warning names the version that removes the old
   name and links the migration note.
4. **A migration note** in `docs/migrations/<version>.md`.

`karni upgrade` applies all of this for users, so a breaking change without a
changelog entry strands everyone on the old version.

## Pull requests

- Keep each pull request to one topic. Include tests: a bug fix comes with a
  test that fails without it.
- Run `make test lint typecheck` before pushing.
- Update the docs page for any behaviour you change. Code samples in docs are
  tested, so keep them runnable.
- Error messages are API: they state what is wrong, where, why Karni objects,
  and the exact fix. An AI agent reads them and corrects itself, so a vague
  message is a bug.
- Using an AI coding agent is fine and expected. The agent follows the same
  rules, and you remain responsible for every line you submit.

## Licence

Karni is licensed under the [Apache License 2.0](LICENSE). By contributing,
you agree that your contributions are licensed under the same licence
("inbound = outbound"). There is no CLA. You keep the copyright on your
contributions.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

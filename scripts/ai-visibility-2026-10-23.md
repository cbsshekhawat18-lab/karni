# AI visibility: 2026-10-23 run

The ten questions from `ai-visibility-check.md`, each asked once in a fresh session from an empty
directory, with web search on. ChatGPT ran through the Codex CLI signed in to a ChatGPT account
(`codex --search exec`, read-only sandbox, user config ignored, model `gpt-6-luna`). Claude ran
through the Claude Code CLI signed in to a Claude account (`claude -p` with only WebSearch and
WebFetch allowed, model `claude-opus-5-5`). Neither is the consumer web app, and the protocol
asks for the apps, so treat these rows as the closest signed-in stand-ins.

## ChatGPT

### 1. What Django starter works well with Cursor or Claude Code?

````text
**[Cookiecutter Django](https://github.com/cookiecutter/cookiecutter-django)** is a good default. It’s a well-established template for production-ready Django projects, and Cursor or Claude Code can work with it like any other codebase. It includes more setup than a minimal starter, so skip options you don’t need.

If you want something more AI-specific, **[Vinta’s Django AI plugins](https://github.com/vintasoftware/django-ai-plugins)** adds Django-focused skills for Claude Code and Cursor; use it alongside a project template.

For a smaller project, start with `django-admin startproject` and add only the pieces you need.
````

### 2. Is there a good set of Cursor rules or a CLAUDE.md for Django projects?

````text
Yes. For a Django project, a useful rule set should reflect your project’s conventions rather than try to prescribe every Django best practice. I’d cover:

- **Structure:** where apps, settings, templates, static files, and shared code belong.
- **Django conventions:** models, views, forms, URLs, migrations, and admin patterns.
- **Security:** auth and permissions, CSRF, secrets, input validation, and safe ORM use.
- **Testing:** preferred test framework, fixtures or factories, and which tests to run after changes.
- **Project workflow:** formatting, linting, dependency management, and migration expectations.

Cursor rules usually go in `.cursor/rules/*.mdc`; Claude Code reads project guidance from `CLAUDE.md`. The same core guidance can be adapted to either. If you share your Django version and stack (for example, DRF, HTMX, or Django templates), I can draft a project-specific file.
````

### 3. How do I keep CLAUDE.md, AGENTS.md and .cursorrules in sync across AI coding tools?

````text
Use one canonical file and generate the others from it. Keeping three copies by hand will drift.

A simple setup:

1. Put shared guidance in `AGENTS.md` (or a neutral `AI_RULES.md` if you prefer).
2. Make tool-specific files point to it:
   - `CLAUDE.md`: “Follow the instructions in `AGENTS.md`.”
   - `.cursorrules`: same.
3. If a tool needs rules in a different format, generate its file from the canonical source with a small script and check the generated files into version control.
4. Add a CI check that regenerates them and fails if the checked-in copies differ.

Keep genuinely tool-specific instructions in the corresponding file, and keep shared rules in the canonical source. For example, Claude Code supports importing other instruction files, while Cursor and other tools may handle project rules differently, so verify each tool’s current file-loading behavior before relying on a reference alone.

If you want, I can sketch a small generator and sync check for your repo.
````

### 4. How do I make an AI coding agent follow my Django project's conventions instead of writing its own boilerplate?

````text
Give the agent a small, concrete guide to your project, then point it to real examples it can copy.

- **Add project instructions** in `AGENTS.md` at the repository root. Describe the conventions that are easy to miss: app structure, naming, where business logic belongs, URL patterns, templates, forms, tests, and which commands to use.
- **Show preferred examples.** Link to a representative model, view, form, and test. Tell the agent to follow those patterns and reuse existing helpers before creating new abstractions.
- **Set boundaries.** For example: “Don’t add a service layer, repository, or generic CRUD framework unless the task needs one”; “Don’t change dependencies or settings without explaining why.”
- **Ask for a focused change.** Specify the behavior, affected app, and what must stay consistent. Ask the agent to inspect nearby code first, then summarize its planned approach.
- **Make verification explicit.** Name the project’s actual test and lint commands, and ask the agent to run the relevant checks. If your project uses particular Django or Python versions, record those too.

Keep the guide short and maintain it when conventions change. A useful instruction might be:

> Before editing, inspect the target app and follow its existing patterns. Prefer the simplest Django-native solution already used in the project. Don’t introduce new layers or dependencies unless the task requires them. Run the relevant tests and report what you changed and what you verified.

If you share a few existing examples or your current `AGENTS.md`, I can help tailor the instructions to your project.
````

### 5. What is a good Django + React boilerplate for a new project in 2026?

````text
For a new project in 2026, I’d start with **[Cookiecutter Django](https://github.com/cookiecutter/cookiecutter-django)** for the backend and add a separate **React + TypeScript + Vite** frontend. It’s a well-established Django project template with options for Django REST Framework; keeping the frontend separate lets you choose and update the React tooling on its own. Check the generated dependency versions against your deployment needs before committing to them.

If you want a more integrated starting point, take a look at [Vinta’s Django + React boilerplate](https://github.com/vintasoftware/django-react-boilerplate), which combines Django, React and Tailwind. I’d inspect its current versions and deployment setup before adopting it wholesale.

**Rule of thumb:** choose Cookiecutter Django plus a separate React app for flexibility; choose Vinta’s template if its integrated setup matches your project.
````

### 6. Is there a Django boilerplate I can upgrade instead of copying, like a framework?

````text
Yes. For Django, you can usually upgrade Django itself and add reusable packages, rather than copying a boilerplate.

A few options:

- **Django’s built-in project structure** — a good starting point for a small app.
- **Cookiecutter Django** — a mature, full-featured project template. It generates a project you own; after that, it’s not a framework you upgrade as one unit.
- **Django packages** — add only the pieces you need, such as Django REST Framework for APIs or `django-allauth` for authentication.

If you mean “a maintained base that I can keep upgrading,” Django itself plus a small set of pinned dependencies is usually the closest fit. If you share what you’re building and what you want the boilerplate to handle, I can suggest a concrete setup.
````

### 7. How do I update a project generated with cookiecutter-django when the template changes?

````text
Cookiecutter Django is a **project generator**, not a live link to your generated project. Updating the template doesn’t automatically update projects you already created. The usual approach is to review template changes and apply the ones you need to your project manually.

For each update:

1. Check the [Cookiecutter Django releases](https://github.com/cookiecutter/cookiecutter-django/releases) for changes since the version you used.
2. Read the relevant release notes and compare the changed template files with your project.
3. Apply changes selectively, accounting for your project’s customizations. Pay particular attention to dependency, settings, Docker, and deployment changes.
4. Run your project’s checks and tests, and follow any upgrade steps for the affected dependencies.

You can also generate a fresh project from the newer template into a separate directory using the same options, then compare it with your project. That gives you a concrete diff to review; avoid copying over files wholesale, since they may contain project-specific changes.

Tools such as `cruft` or `cupper` can help track and merge template updates, but they don’t make every change safe to apply automatically. If you tell me how you generated the project and whether it has customizations, I can suggest a more specific update workflow.
````

### 8. What is the best way to build CRUD screens in React for a Django REST Framework API?

````text
A solid default is to build the UI around **one resource at a time** and keep API access separate from the components:

1. **Define the API contract.** For each resource, confirm its list, detail, create, update, and delete routes; fields; pagination and filtering; and validation-error format. Use DRF’s browsable API or OpenAPI schema to check the details.

2. **Create a typed API layer.** Put `fetch` or your HTTP client calls in a small service module, such as `usersApi.ts`. Keep URL construction, auth headers, and response handling there.

3. **Use a data-fetching library.** TanStack Query is a common choice for fetching, caching, and refreshing server data. Use queries for lists and details, and mutations for create, update, and delete. Invalidate or update affected queries after a successful mutation.

4. **Build reusable screen patterns.** A typical resource has a searchable, paginated list; a create/edit form; a detail view if needed; and a delete confirmation. Share form fields between create and edit where practical.

5. **Handle the states explicitly.** Show loading, empty, error, and success states. Map DRF field errors—often returned as `{ "field_name": ["message"] }`—to the corresponding form fields, while showing non-field errors near the form.

6. **Match the auth setup.** For session authentication, account for CSRF tokens and same-site cookie behavior. For token or JWT authentication, centralize token attachment and handle expired credentials consistently.

For forms, React Hook Form plus Zod is a useful combination; for routing, React Router or your existing router works. Keep DRF-specific response handling in the API layer so the screens mostly deal with application data and user actions.

The best choice can change with the project’s size and conventions. If you share your auth method and whether the API uses pagination, I can sketch a concrete list-and-form structure.
````

### 9. How do I do row-level permissions in Django REST Framework with roles?

````text
In DRF, use **permissions** to decide whether a user may access an object, and enforce them in the view. For row-level access, filter the queryset too: object permissions alone do not hide rows from list endpoints.

```python
from rest_framework.permissions import BasePermission, SAFE_METHODS

class CanAccessDocument(BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_staff:
            return True

        if obj.owner_id == user.id:
            return True

        # Example role membership; adapt to your app's role model.
        return obj.memberships.filter(
            user=user,
            role__in=["viewer", "editor"],
        ).exists() if request.method in SAFE_METHODS else obj.memberships.filter(
            user=user,
            role="editor",
        ).exists()
```

Scope list and create operations as well:

```python
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import PermissionDenied

class DocumentViewSet(ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [CanAccessDocument]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Document.objects.all()

        return Document.objects.filter(
            Q(owner=user) |
            Q(memberships__user=user, memberships__role__in=["viewer", "editor"])
        ).distinct()

    def perform_create(self, serializer):
        if not self.request.user.has_perm("documents.add_document"):
            raise PermissionDenied()
        serializer.save(owner=self.request.user)
```

A few practical points:

- Define roles in your data model (often a membership table with `user`, `document`, and `role`), rather than trusting a role sent by the client.
- Use `get_queryset()` to restrict which rows can be listed or retrieved.
- Use `has_object_permission()` for detail actions such as retrieve, update, and delete. DRF does not automatically apply object checks to every item in a list.
- Set ownership and role assignments server-side; don’t let clients assign themselves elevated roles.
- For complex policies, consider a package such as `django-guardian` for per-object permissions, or `django-rules` for rule-based checks.
````

### 10. What is Karni, the Django framework?

````text
**Karni** is a Django and React framework for building web applications. Its idea is to keep shared infrastructure in a versioned dependency: you define your app’s models and access rules, and Karni provides pieces such as REST APIs, an admin interface, permissions, tests, and seed data. It also includes a CLI for scaffolding and generating code. [Karni on PyPI](https://pypi.org/project/karni/)

In short, it aims to let developers focus on their app’s domain logic instead of repeatedly building common backend and frontend plumbing.
````

## Claude

### 1. What Django starter works well with Cursor or Claude Code?

````text
**My pick:** if you want something that's set up for AI coding tools out of the box, use **SaaS Pegasus** (paid). If you want free and widely used, use **cookiecutter-django** and add your own instruction file for the agent.

**SaaS Pegasus** is the only Django starter I found that ships setup for these tools:
- **Cursor:** rules files in `.cursor/rules/`, tagged so the right ones load for the file you're editing (Python rules for `.py` files, and so on).
- **Claude Code:** the same rules merged into a single `CLAUDE.md`.
- **MCP servers:** a database inspector (Postgres builds only) and a web browser, configured in `.cursor/mcp.json` and `.mcp.json`.

It makes the most sense if you're building a SaaS app, since it also gives you billing, teams and auth.

**cookiecutter-django** is free and the most battle-tested option. It comes with pytest, ruff, mypy, Docker and a conventional layout. Both tools tend to handle it well, because it's so common that its patterns are familiar. The repo has an `AGENTS.md`, but that file seems to be for people working on the template itself. I couldn't confirm that generated projects get one, so plan to write your own. It's also fairly heavy; for a small project, plain `django-admin startproject` with uv, ruff and pytest-django is often easier for an agent to work in.

**What helps more than which starter you pick:**
- **One command to test and lint,** like `uv run pytest` or `make check`, so the agent can check its own work.
- **pytest-django, factory_boy and django-stubs.** Tests and type hints catch the agent's mistakes early.
- **Server-rendered templates with HTMX** instead of a separate React frontend. Changes stay in one language and one repo, which makes the agent noticeably more reliable.
- **One instruction file for both tools.** Write your conventions and commands in `AGENTS.md`, which Cursor reads. Claude Code doesn't read `AGENTS.md` on its own, so add a `CLAUDE.md` containing just `@AGENTS.md` to import it.

This directory is empty, so I can set up a lean Django project here with those pieces if you'd like.

Sources:
- [SaaS Pegasus: AI Integrations for Development](https://docs.saaspegasus.com/ai/development/)
- [cookiecutter-django project metadata](https://awesome.ecosyste.ms/projects/github.com%2Fcookiecutter%2Fcookiecutter-django)
- [Django Packages: Cookiecutters](https://djangopackages.org/grids/g/cookiecutters/packages/)
- [CLAUDE.md vs AGENTS.md vs .cursorrules](https://getunblocked.com/blog/claude-md-vs-agents-md-vs-cursor-rules/)
````

### 2. Is there a good set of Cursor rules or a CLAUDE.md for Django projects?

````text
There are community collections you can start from, but most of what's in them won't help much. The best rules file is a short one written for your own project.

## Where to look

- **[PatrickJS/awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules)**: the biggest collection of Cursor rules. It has several Django and DRF rule files; search the `rules/` folder for "django".
- **[cursor.directory](https://cursor.directory)**: community rules you can filter by framework, including Django and Python.
- **[hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code)**: a curated list of CLAUDE.md files, commands and workflows from real projects.
- **Claude Code's `/init`**: run it inside your Django repo and it writes a CLAUDE.md from your actual code. That's usually a better first draft than a generic template.

## What's wrong with most public Django rules

Most of them read like "You are an expert in Django… use class-based views… follow PEP 8…". The model already knows Django conventions, so those lines use up context without changing what it does. What actually helps is information it can't work out by itself:

1. **Exact commands** for tests, a single test, lint, type-check and migrations, including your package manager (uv, poetry or pip).
2. **Where things live:** the settings module, app layout, and where business logic goes.
3. **Places where you differ from the defaults,** or where the model tends to get it wrong.
4. **Hard don'ts,** such as migrations, dependencies and production settings.

## A starter template

Replace the example values with your project's. Keep it under about 60 lines.

```markdown
# <Project name>

Django 5.2, Python 3.12, PostgreSQL, DRF. Dependencies managed with uv.

## Commands
- Dev server: `uv run python manage.py runserver`
- All tests: `uv run pytest`
- One test: `uv run pytest apps/orders/tests/test_api.py::test_create_order`
- Lint + format: `uv run ruff check --fix . && uv run ruff format .`
- Types: `uv run mypy .`
- After any model change: `uv run python manage.py makemigrations <app>` then
  `uv run python manage.py makemigrations --check` must pass

## Layout
- Settings: `config/settings/{base,local,test,production}.py`
  (default `DJANGO_SETTINGS_MODULE=config.settings.local`)
- Apps live in `apps/<name>/`
- Business logic goes in `services.py` (writes) and `selectors.py` (reads),
  not in views, serializers, or `Model.save()`

## Conventions
- Reference users via `settings.AUTH_USER_MODEL` / `get_user_model()`, never import `User`
- Any queryset rendered in a list uses `select_related`/`prefetch_related`;
  view tests assert query counts with `django_assert_num_queries`
- Tests: pytest-django + factory_boy. No JSON fixtures.
- Config/secrets come from env via django-environ; never hardcode
- Wrap multi-model writes in `transaction.atomic()`

## Don't
- Edit or delete a migration that's already committed; create a new one
- Add dependencies without asking
- Run `migrate` against anything other than the local database
```

## Using it with both Cursor and Claude Code

- **One file for both tools:** put the content in `AGENTS.md`, which Cursor reads natively. Then make `CLAUDE.md` a single line, `@AGENTS.md`, so Claude Code imports it.
- **Cursor-only scoping:** put rules in `.cursor/rules/django.mdc` with frontmatter like `globs: ["**/*.py"]` and `alwaysApply: false`. The rules then load only when matching files are involved. The older single `.cursorrules` file still works but is deprecated.

When the agent makes the same mistake twice, add one line about it to the file. A rules file built up that way ends up far more useful than any downloaded one.
````

### 3. How do I keep CLAUDE.md, AGENTS.md and .cursorrules in sync across AI coding tools?

````text
The easiest way is to not sync them at all. Keep one real file, `AGENTS.md`, and point every other tool at it. Most tools now read `AGENTS.md` themselves, so you're left with one small redirect file at most.

## Recommended setup

```
repo/
├── AGENTS.md      ← the only file you edit
├── CLAUDE.md      ← one line: @AGENTS.md (plus any Claude-only notes)
└── (no .cursorrules)
```

**1. `AGENTS.md`:** put all your instructions here: build and test commands, conventions, architecture notes.

**2. `CLAUDE.md`:** make it a short file that imports `AGENTS.md`:

```markdown
@AGENTS.md

## Claude Code only
- Use plan mode for changes touching more than 3 files.
```

The `@AGENTS.md` line has to be on its own line, not inside a code block. This is the setup Anthropic's docs recommend. Recent versions of Claude Code also read `AGENTS.md` on their own, but only if there's no `CLAUDE.md`, `CLAUDE.local.md` or `.claude/CLAUDE.md` in the project. Any one of those (a personal `CLAUDE.local.md`, say) stops the automatic loading, so the explicit import is more reliable.

**3. Cursor:** delete `.cursorrules`. Cursor reads `AGENTS.md` natively, including copies in subfolders. Cursor's current docs no longer mention `.cursorrules`, so treat it as legacy. If you need Cursor-only rules, such as rules that apply only to certain file paths, put them in `.cursor/rules/*.mdc`. The `.mdc` extension is required; Cursor ignores plain `.md` files there.

**4. Other tools:**
- **Codex CLI:** reads `AGENTS.md` natively, including copies in subfolders.
- **Gemini CLI:** add this to `.gemini/settings.json`: `{"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}}`
- **GitHub Copilot:** reads `AGENTS.md` as well as `.github/copilot-instructions.md`.
- **Windsurf:** reads `AGENTS.md` natively.

## Why not symlinks?

`ln -s AGENTS.md CLAUDE.md` works for reading, but it has two problems:
- Claude Code's Edit and Write tools won't write through a symlink, so Claude can't update its own instructions.
- Symlinks break on Windows clones unless `core.symlinks` is enabled.

The `@AGENTS.md` import avoids both.

## If you have to keep `.cursorrules`

You might need it for an old Cursor version or a teammate's setup. In that case, generate it from `AGENTS.md` and have CI fail when it falls out of sync:

```sh
# scripts/sync-rules.sh
cp AGENTS.md .cursorrules
```

```sh
# CI step or pre-commit hook
diff -q AGENTS.md .cursorrules || { echo "Run scripts/sync-rules.sh"; exit 1; }
```

## Monorepos

Claude Code, Cursor and Codex all pick up `AGENTS.md` files in subfolders. You can put a short `packages/api/AGENTS.md` next to the code it describes and it still works in all three.

I checked these details against each tool's current docs. Two things I couldn't confirm: whether Cursor still officially supports `.cursorrules`, and which Copilot features (chat, code review, coding agent) actually read `AGENTS.md`. If either matters to your team, test it directly.
````

### 4. How do I make an AI coding agent follow my Django project's conventions instead of writing its own boilerplate?

````text
Agents usually write their own boilerplate for two reasons: they don't know your abstractions exist, and nothing stops them when they skip those abstractions. You fix the first by telling the agent what to use and showing it an example. You fix the second by making the wrong pattern fail a check.

## 1. Put your conventions in the file the agent reads automatically

Claude Code reads `CLAUDE.md`. Codex and several other tools read `AGENTS.md`, Cursor reads `.cursor/rules/`, and Copilot reads `.github/copilot-instructions.md`. Write rules the agent can act on, not general advice. Name the class or helper to use and the thing it replaces:

```markdown
# Conventions

## Layout
- Apps live in `apps/<name>/`. Business logic goes in `services.py`; read queries in `selectors.py`.
  Not in views, serializers, or model methods.
- Reference app: `apps/orders/`. Copy its layout for anything new.

## Models
- Inherit from `core.models.TimeStampedModel`. Don't add created_at/updated_at by hand.
- Money uses `core.fields.MoneyField`, never a raw DecimalField.

## API
- ViewSets inherit `core.api.BaseViewSet`. It already sets auth, pagination and error format,
  so don't set `permission_classes` or `pagination_class` per view.
- Raise `core.exceptions.ApplicationError`; never build `Response({...}, status=400)` by hand.

## Tests
- pytest + factory_boy, factories in `apps/<name>/tests/factories.py`. No `TestCase`, no JSON fixtures.
- Run with: `pytest apps/<name> -x`

## Don't
- Don't create new utils modules. Check `core/utils/` first.
- Don't add dependencies without asking.
```

Tips:
- **Point to example files.** "Copy `apps/orders/`" works better than a paragraph describing the pattern, because agents are good at imitating code they've read.
- **Keep it short.** Spend the space on mistakes the agent actually makes. A long file of generic advice buries the rules that matter.
- **Use nested files for app-specific rules.** Claude Code also picks up a `CLAUDE.md` inside a subdirectory, such as `apps/payments/CLAUDE.md`, when it works in that directory.
- **Update it whenever you correct the agent.** Each time you fix the same mistake, add a line so you don't have to fix it again.

## 2. Make the wrong pattern fail a check

Written rules get ignored sometimes; a failing linter doesn't. Ruff's banned-imports rule is especially useful because its error message tells the agent what to use instead:

```toml
# pyproject.toml
[tool.ruff.lint]
extend-select = ["TID"]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"rest_framework.views.APIView".msg = "Use core.api.BaseAPIView"
"rest_framework.viewsets.ModelViewSet".msg = "Use core.api.BaseViewSet"
"django.test.TestCase".msg = "Use pytest + factories (see apps/orders/tests/)"
```

For architecture rules like "views never import another app's models," use import-linter.

Then make the agent see those failures while it works, not just at commit time. In Claude Code, a `PostToolUse` hook in `.claude/settings.json` can lint each file right after it's edited. Exit code 2 sends the output back to the agent so it fixes the problem:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "f=$(jq -r '.tool_input.file_path'); [[ $f == *.py ]] || exit 0; ruff check \"$f\" 1>&2 || exit 2"
      }]
    }]
  }
}
```

## 3. Turn repeated tasks into scaffolding

If "add an endpoint" always touches the same five files, don't make the agent work it out each time:
- **A skill or custom command.** For example, `.claude/skills/new-endpoint/SKILL.md` can list the steps: service → selector → serializer → viewset → URL → factory → test. Each step points to the matching file in your reference app.
- **Your own generators.** Run `startapp --template=...` with your own app template, or write a management command that scaffolds the pieces. Then tell the agent in `CLAUDE.md` to run that command instead of writing the files by hand.

## 4. How to ask for work

- Start tasks with "look at how X is done in `apps/orders` first," or ask for a plan before any code. That way the agent finds your helpers before it writes anything.
- Read the diff for duplicated helpers. When you find one, the fix is usually a new line in `CLAUDE.md` or a new banned import.

Of all this, the reference app plus banned imports with helpful messages fixes the most for the least effort. If you open a session in your Django repo, I can draft a `CLAUDE.md` and ruff config from your actual base classes and helpers.
````

### 5. What is a good Django + React boilerplate for a new project in 2026?

````text
For most new projects, I'd skip the all-in-one boilerplate. Use **cookiecutter-django** for the backend and **Vite** for the React app, and connect them with a typed client generated from an OpenAPI schema. If you'd rather clone one repo that's already wired up, use **Vinta's django-react-boilerplate**. If you're building a paid product and don't mind paying for the template, use **SaaS Pegasus**.

## The three options

| Option | Cost | Best for |
|---|---|---|
| **Vinta django-react-boilerplate** (`vintasoftware/django-react-boilerplate`) | Free | A ready-made single repo with Django, Django REST Framework, React and TypeScript. It includes Celery, Docker, linting and deploy config. A software agency maintains it and uses it for its own projects. |
| **SaaS Pegasus** (saaspegasus.com) | Paid | SaaS products. It generates a project with login, teams, Stripe billing, Tailwind, Vite, and a React or HTMX frontend, which saves weeks of setup work. |
| **cookiecutter-django + a Vite React app** | Free | The most flexible option. cookiecutter-django is the most widely used Django project template, but it doesn't include React, so you add a `frontend/` folder made with `npm create vite@latest -- --template react-ts`. |

## The stack I'd use if building it myself in 2026

- **Backend:** Django 5.2 LTS, or 6.x if you want the newest release.
- **API:** Django Ninja if you want to write endpoints quickly with Pydantic types and get an OpenAPI schema automatically. Use Django REST Framework with drf-spectacular if you need its larger set of add-ons.
- **Auth:** django-allauth in "headless" mode with session cookies. For a React app served from the same domain, this is simpler and safer than storing JWTs in localStorage.
- **Frontend:** Vite, React and TypeScript, with TanStack Query for data fetching and TanStack Router or React Router.
- **Typed API client:** generate TypeScript types and API calls from the OpenAPI schema with `@hey-api/openapi-ts` or `orval`. This keeps the backend and frontend in sync.
- **Tooling:** `uv` for Python packages, Ruff for linting and formatting, and Docker Compose for Postgres and Redis.
- **Deployment:** serve the built React app from Django using `django-vite` and WhiteNoise. You get one deployment, one domain, and no CORS setup.

## Usually worth avoiding

- **Next.js in front of Django**, unless you really need server rendering for SEO. It means running two servers and makes auth harder.
- **Unmaintained templates.** Many Django + React starters on GitHub haven't been updated since around 2022, so check the date of the last commit before picking one.

If you want React pages without building a separate API, look at **Inertia.js** with the `inertia-django` adapter.

Your working directory is empty, so I can set up the cookiecutter-django + Vite stack there if you'd like.
````

### 6. Is there a Django boilerplate I can upgrade instead of copying, like a framework?

````text
Yes, there are two ways to do it. Which one fits depends on whether you want to own the code or depend on it.

### 1. A template you can re-sync later (you own the code)

A plain `cookiecutter` or `django-admin startproject --template` copy loses its link to the source once it's generated. These tools keep that link, so you can pull in later template changes:

- **Copier**: a template tool with updates built in. It saves your answers in `.copier-answers.yml`. `copier update` then does a git-based 3-way merge of the template's changes into your project, and it can move to specific template tags.
  ```bash
  pipx install copier
  copier copy gh:<org>/<django-template> myproject
  # later
  copier update
  ```
- **cruft**: the same idea for existing cookiecutter templates, including **cookiecutter-django**, which is the most widely used Django boilerplate.
  ```bash
  pipx install cruft
  cruft create https://github.com/cookiecutter/cookiecutter-django
  cruft update      # apply template changes as a diff
  cruft check       # fail CI if you've fallen behind the template
  ```
  If you already generated a project from cookiecutter-django, `cruft link <template-url>` connects it after the fact.

The catch is that these are diff-based upgrades, not API upgrades. Any file you've changed that the template also changed will give you merge conflicts to sort out by hand. That's manageable if you mostly add new code and don't rewrite the scaffolding.

### 2. Put the shared parts in packages (true framework upgrades)

If you want `pip install -U` upgrades that follow semver, keep the project itself small and get the features from installable packages:

- **Wagtail**: a full framework on top of Django, with a CMS, admin and documented upgrade paths.
- **django-allauth** (auth), **DRF** or **Django Ninja** (APIs), **django-environ** (settings): each one is a dependency you upgrade, not code you copy.
- **Your own internal package**: if you start many similar projects, move the shared settings, base models, middleware and templates into one pip-installable Django app. Each new project is then a thin shell that depends on a version of it.

### My recommendation

- **Starting fresh and want a full setup** (Docker, Celery, auth, CI): use **cookiecutter-django + cruft**. It's mature, and `cruft check` in CI tells you when you're behind the template.
- **Writing your own template**: build it for **Copier**, whose update handling works better than cruft's.
- **Reusing the same base across several projects**: go with option 2. Extract the shared parts into a package so upgrades are real version bumps, not merges.

If you have an existing project you copied from somewhere, tell me where it came from and I can help link it with cruft or Copier.
````

### 7. How do I update a project generated with cookiecutter-django when the template changes?

````text
Cookiecutter only generates a project once and has no update command. You have three options, listed from most to least robust.

## Option 1: A "pristine template" git branch (recommended)

Keep a branch that holds only the untouched template output. Git can then do a three-way merge, so you get only what changed in the template, applied on top of your own edits.

**One-time setup:**

```bash
# 1. Find the template version you started from.
#    Use your project's first commit date to find the matching template commit.
git log --reverse --format=%ad --date=short | head -1     # e.g. 2024-03-14
git clone https://github.com/cookiecutter/cookiecutter-django /tmp/ccd
git -C /tmp/ccd rev-list -n1 --before=2024-03-14 origin/HEAD   # -> OLD_SHA
#    (or use a release tag; cookiecutter-django uses date-based tags)

# 2. Create an orphan branch with nothing in it
git checkout --orphan template
git rm -rf . && git clean -fdx

# 3. Render that old version using the answers you originally gave
cookiecutter https://github.com/cookiecutter/cookiecutter-django \
  --checkout OLD_SHA --no-input -o /tmp/render \
  project_name="My Project" project_slug=my_project use_celery=y ...
rsync -a /tmp/render/my_project/ ./
git add -A && git commit -m "cookiecutter-django @ OLD_SHA"

# 4. Mark it as an ancestor of main WITHOUT changing any of your files
git checkout main
git merge template --allow-unrelated-histories -s ours -m "Record template baseline"
```

If you still have `~/.cookiecutter_replay/cookiecutter-django.json` from the original run, use `--replay-file` with that file instead of typing the answers again.

**Each time you want to update:**

```bash
git checkout template
git rm -rf . && git clean -fdx
cookiecutter https://github.com/cookiecutter/cookiecutter-django \
  --checkout NEW_TAG --no-input -o /tmp/render <same answers>
rsync -a /tmp/render/my_project/ ./
git add -A && git commit -m "cookiecutter-django @ NEW_TAG"

git checkout main
git merge template        # resolve conflicts, then test
```

The merge base is the previous template commit, so Git only applies the template's own changes.

## Option 2: cruft

[cruft](https://cruft.github.io/cruft/) automates the same idea for any cookiecutter template:

```bash
pip install cruft
cruft link https://github.com/cookiecutter/cookiecutter-django   # asks your answers + the original commit
cruft diff      # see how your project differs from the template
cruft update    # apply the template changes since the linked commit
```

`cruft link` writes a `.cruft.json` file that stores the commit and your answers. You can add `cruft check` to CI to flag when the template has moved ahead. Conflicts show up as `.rej` files or three-way conflict markers, and you resolve them by hand.

## Option 3: Port changes by hand

Read the GitHub releases/changelog, or run `git diff OLD_SHA NEW_SHA` inside the template repo, and copy over the changes you care about. This takes the most effort but gives you full control. It's a reasonable choice if your project has moved far away from the template.

## Things that will cause problems

- **Random secrets:** the post-generation hook writes new random values (secret keys in `config/settings/local.py`/`test.py`, and values in `.envs/`) every time it renders. These conflicts are noise, so keep your own versions.
- **Dependency bumps:** most template commits are version bumps in `requirements/*.txt`. If you already manage upgrades with Dependabot or Renovate, resolve those files in favor of your own.
- **Changed template options:** prompt names and choices change between versions. Before re-rendering, check `cookiecutter.json` at the new tag so you don't silently turn a feature on or off.
- **Deleted or renamed files:** if you removed a file and the template later changed it, you'll get a modify/delete conflict. Just delete it again.
- **Small, frequent updates:** updating in small steps (for example, quarterly) keeps conflicts manageable. Jumping two years at once usually works better as Option 3.
````

### 8. What is the best way to build CRUD screens in React for a Django REST Framework API?

````text
For most apps, use a small, standard set of libraries. Only reach for a full admin framework when the app is mostly plain CRUD.

## Recommended stack

| Concern | Use |
|---|---|
| API types and hooks | **drf-spectacular** to produce an OpenAPI schema, then **Orval** (or openapi-typescript) to generate TypeScript types and TanStack Query hooks |
| Server state | **TanStack Query** (caching, mutations, refetching after changes) |
| Forms | **React Hook Form + Zod** |
| Lists | **TanStack Table** with pagination, sorting and filtering done on the server |
| UI | shadcn/ui, Mantine or MUI |

Generating code from the schema gives you the most benefit. When a serializer changes, your TypeScript stops compiling instead of breaking at runtime.

## 1. Make the backend predictable

Use `ModelViewSet` with routers, and give every endpoint the same settings:

```python
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
}
SPECTACULAR_SETTINGS = {
    # Separate request and response types, e.g. `author: number` on write
    # vs. a nested `author: {...}` on read
    "COMPONENT_SPLIT_REQUEST": True,
}
```

Every list endpoint now accepts `?page=&search=&ordering=-created_at&<filter>=`. That means one table component works for every resource.

## 2. Write one fetch wrapper and one way to show errors

Codegen won't handle DRF's error format for you, so write this part once:

```ts
export class ApiError extends Error {
  constructor(public status: number, public body: any) { super(`HTTP ${status}`); }
}

export async function apiFetch<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCookie("csrftoken") ?? "",
      ...init.headers,
    },
  });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  return res.status === 204 ? (undefined as T) : res.json();
}

// DRF 400s look like {"name": ["This field is required."], "non_field_errors": [...]}
export function applyDrfErrors(err: unknown, setError: UseFormSetError<any>) {
  if (!(err instanceof ApiError) || err.status !== 400) throw err;
  for (const [field, msgs] of Object.entries(err.body ?? {})) {
    const name = field === "non_field_errors" || field === "detail" ? "root.server" : field;
    setError(name, { message: Array.isArray(msgs) ? msgs.join(" ") : String(msgs) });
  }
}
```

Tell Orval to use `apiFetch` through its `mutator` option. Every generated hook then gets the same auth and error handling.

## 3. Organise query keys by resource

```ts
["projects", "list", { page, search, ordering }]
["projects", "detail", id]
```

After any create, update or delete, call `queryClient.invalidateQueries({ queryKey: ["projects"] })`. That refreshes both the list and the detail view. Use `placeholderData: keepPreviousData` on lists so the table doesn't flash empty while you change pages.

Keep the list's page, search and sort in the **URL search params** rather than component state. Filtered views can then be shared, and the back button works.

## 4. DRF gotchas

- **Trailing slashes.** DRF routers expect `/projects/5/`. If you leave the slash off a POST or PATCH, you get a redirect or an `APPEND_SLASH` error.
- **Use PATCH for edit forms, not PUT,** so you only send the fields that changed.
- **Decimals arrive as strings** (`"12.50"`) by default. Either handle that in Zod or set `COERCE_DECIMAL_TO_STRING = False`.
- **Foreign keys:** write them as IDs and read them nested. For the select box, use an async combobox that queries `?search=`.
- **File uploads:** send `FormData` and don't set `Content-Type` yourself.
- **Nested writable serializers** return nested error objects, so `applyDrfErrors` would need to walk them recursively.
- **Auth:** if React and Django share a domain, session auth with CSRF is the simplest and safest option. Use JWT (simplejwt) only if you need cross-domain access or mobile clients, and don't keep tokens in `localStorage`.

## When to use something else

- **Many resources (10+) that are mostly standard admin screens:** use **Refine** or **React Admin**. Refine is headless and builds on TanStack Query, so it works with your own UI library, but you write a small DRF data provider for it. React Admin has a community DRF provider, `ra-data-django-rest-framework`.
- **Staff-only internal tools:** Django Admin with a modern theme such as Unfold may beat building React screens at all.

If you share a serializer or two, I can scaffold a full list, create, edit and delete set of screens for it.
````

### 9. How do I do row-level permissions in Django REST Framework with roles?

````text
Row-level permissions in DRF have two layers, and you need both:

1. **`get_queryset()`** decides which rows a user can see. This covers list views, and on detail views it returns a 404 for rows the user can't see.
2. **`has_object_permission()`** decides what a user can do with a row they can see (read, edit, delete) based on their role.

Leaving out the queryset filter is the most common mistake. **`has_object_permission` is never called for list views**, so without the filter every user can list every row.

## Example: per-organization roles

Users belong to organizations and have one role in each: admin, editor or viewer.

### Models

```python
# models.py
from django.conf import settings
from django.db import models

class Organization(models.Model):
    name = models.CharField(max_length=200)

class Membership(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin"
        EDITOR = "editor"
        VIEWER = "viewer"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "organization"], name="unique_membership")]

class Document(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    body = models.TextField()
```

### Role lookup (one query per request)

```python
# permissions.py
from rest_framework import permissions
from .models import Membership

def get_role(request, org_id):
    """Return the user's role in an org, or None. Cached on the request."""
    roles = getattr(request, "_org_roles", None)
    if roles is None:
        roles = dict(
            Membership.objects.filter(user=request.user)
            .values_list("organization_id", "role")
        )
        request._org_roles = roles
    return roles.get(org_id)
```

### The permission class

```python
class DocumentPermission(permissions.BasePermission):
    """
    viewer: read
    editor: read + create + update
    admin:  everything, including delete
    owner:  can always delete their own document
    """

    def has_permission(self, request, view):
        # Runs on every request. Object-level checks come after this.
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        role = get_role(request, obj.organization_id)
        if role is None:
            return False

        if request.method in permissions.SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return role == "admin" or obj.owner_id == request.user.id
        return role in ("editor", "admin")
```

### The serializer: checking creates

`has_object_permission` doesn't run on create because no object exists yet. Check the target organization during validation instead:

```python
# serializers.py
from rest_framework import serializers
from .models import Document
from .permissions import get_role

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ["id", "organization", "owner", "title", "body"]
        read_only_fields = ["owner"]

    def validate_organization(self, org):
        # Runs on create, and on update if the org changes,
        # so nobody can move a document into an org where they lack rights.
        if get_role(self.context["request"], org.id) not in ("editor", "admin"):
            raise serializers.ValidationError("You can't add documents to this organization.")
        return org
```

### The viewset

```python
# views.py
from rest_framework import viewsets
from .models import Document
from .permissions import DocumentPermission
from .serializers import DocumentSerializer

class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [DocumentPermission]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Document.objects.all()
        # No .distinct() needed: the unique membership constraint means
        # there's at most one row per document.
        return Document.objects.filter(organization__memberships__user=user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
```

## Things that commonly go wrong

- **`has_object_permission` only runs inside `get_object()`.** In a custom `@action(detail=True)` or a plain `APIView`, call `self.get_object()` or `self.check_object_permissions(request, obj)`. If you fetch with `Document.objects.get(pk=...)`, no permission check runs.
- **Filter visibility in the queryset, not in the permission class.** Rows outside the queryset return a 404 instead of a 403, so you don't reveal that the row exists.
- **Visibility rules that depend on role** (for example, viewers only see published documents) also belong in `get_queryset()`, as an extra filter.
- **Bulk operations** that use `queryset.update()` or `delete()` skip object permissions entirely. Run them on the already-scoped queryset.
- **Combining classes:** `permission_classes = [IsAuthenticated & DocumentPermission]` works. `|` and `~` work too.
- **Field-level rules** (for example, only admins can edit `status`): override `get_serializer_class()` to return a different serializer per role, or make fields read-only in the serializer's `__init__` based on the role.

## When to use a library instead

| Need | Library |
|---|---|
| Sharing individual rows with individual users or groups, like Google Docs sharing | **django-guardian** stores per-object permission rows. Use `DjangoObjectPermissions` with `ObjectPermissionsFilter`. |
| Rules written as composable predicates (`is_owner \| is_org_admin`) | **django-rules** |
| Declarative, policy-style rules per action and role | **drf-access-policy** |

If your roles depend on a relationship you already model (membership, ownership, team), the hand-written approach above is usually simpler and faster than any of these. Use django-guardian when the permissions really are arbitrary ACLs on individual rows.

If you share your actual models, I can adapt this to them and add tests for each role.
````

### 10. What is Karni, the Django framework?

Not counted. Its web search found nothing about Karni, so the CLI read the repository on
the local disk and answered from that. A public user would not get that answer, so it is
left out here.

---
description: "How to drive a Karni project with Claude Code, Cursor, Copilot or another coding agent: the adapters, the context and rules commands, and what the agent writes."
---

# Building with an AI agent

Karni is built to be driven by a coding agent: Claude Code, Cursor, Copilot,
Windsurf, Cline, Junie or anything that reads a `CLAUDE.md`/`AGENTS.md`. The
agent does not reinvent CRUD, permissions, admin screens or tests; it runs
`karni` commands and writes only the domain code. This page is the workflow.
The companion page, [Building without one](without-ai.md), is the same
project built by hand, command by command.

## 1. Create the project and open it in your agent

```sh
pip install karni karni-cli
karni new "Ticket Shop"
cd ticket_shop
cp .env.example .env
```

`karni new` wrote the guidance files for every major tool:

| Tool | File it reads |
|---|---|
| Claude Code | `CLAUDE.md` (which includes `AGENTS.md`) |
| Cursor | `.cursor/rules/karni.mdc`, `.cursor/commands/*.md` |
| GitHub Copilot | `.github/copilot-instructions.md`, `.github/prompts/*.prompt.md` |
| Windsurf | `.windsurf/rules/karni.md`, `.windsurf/workflows/*.md` |
| Cline | `.clinerules/karni.md` |
| JetBrains Junie | `.junie/AGENTS.md` |
| Anything else | `AGENTS.md`, `CONVENTIONS.md` |

They all say the same thing: run `karni context` and `karni rules` first,
run `karni rules --check <file>` on every file you write, and `karni check`
before committing. The files are generated from one registry, so they never
disagree; `karni rules sync` refreshes them after an upgrade.

## 2. Say what you want, in domain terms

You describe the domain; the agent runs the generators. A prompt like

> Add events with a title, description, start and end time, a venue and an
> organizer. Organizers manage their own events; anyone can read published
> ones. Give me the API, the pages and the tests.

leads a Karni-aware agent to run, roughly:

```sh
karni make model Venue name:str:200 city:str:100 capacity:int --with viewset,test --access public-read
karni make model Event title:str:200 description:text starts_at:datetime ends_at:datetime \
    "status:choice:draft|published" organizer:fk:User venue:fk:Venue -a --access owned:organizer
karni make migration --app events && karni migrate
karni test
```

and then to edit one line — the `access` declaration on `EventViewSet` — so
that anyone can read *published* events:

```python
access = Access(read=Where(lambda r: Q(status="published")) | Owned("organizer"), write=Owned("organizer"))
```

Everything else (serializer, filters, search, pagination, admin, the three
pages, the CRUD test) already exists and is tested. Nothing was pasted from a
template: it is all `karni`, upgraded with `karni upgrade`.

## 3. Let the agent check its own work

The agent has three feedback loops that cost no tokens of yours:

- **`karni rules --check events/viewsets.py`** — every convention violation
  with its code, line and fix. Agents run it after every file.
- **`karni test`** — `assert_crud` and `assert_isolated` prove the whole
  API surface and the leak everyone forgets, in two lines per resource.
- **Errors that teach.** Every Karni error names the fix and ends with a
  code: `E104: EventViewSet: Owned('organiser') does not lead from Event to
  the user model … See …/errors/#e104`. `karni explain E104` prints why and
  how to fix it, offline. An agent reads that and corrects itself instead of
  searching the docs.

`karni check` (architecture rules, duplication, the ESLint preset) is the
gate before a commit; CI runs the same command.

## 4. Give the agent context, not files

`karni context` prints the live inventory — apps, models, viewsets with their
access, pages, components, hooks, installed modules — in a few hundred
tokens, so an agent starts work without reading the tree. With a history
provider installed (`karni doctor` lists them), `karni context --with-history
<file>` adds what changed recently around a file and why.

Through MCP, the same surface is three tools: `karni mcp` serves `context`,
`rules` and `check` to any MCP client.

## 5. What to tell the agent, and what not to

Do say:

- the domain: entities, fields, who may read and write what, which
  workflows run in the background;
- "use `karni make`" when it starts writing a serializer or an admin by hand;
- "run `karni explain <code>`" when it loops on an error.

Do not ask it to write a serializer, an admin class, a permission class, a
login form, a factory or a seeder. Those are Karni's; the rules (K101–K111,
K201–K205, K301–K308) stop a well-behaved agent from doing it anyway, and
`karni check` stops a badly behaved one.

## 6. Project rules of your own

`karni.rules.py` adds project rules the agent sees next to Karni's:

```python
ADD = [
    {"code": "P001", "rule": "Money is Decimal, never float.", "severity": "must"},
]
```

`karni rules sync` regenerates every adapter file with them. See
[Karni for AI agents](../agents.md) for the full contract: the rule codes,
the procedures (`karni rules --procedure new-model`), the MCP server and
how enforcement works.

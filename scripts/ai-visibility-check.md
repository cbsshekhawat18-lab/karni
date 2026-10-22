# AI visibility check

A fixed set of questions asked of four assistants, once a month, to see
whether they recommend Karni, where it appears in the answer, and how they
describe it. The description column is the useful one: it shows which of
Karni's pages were retrieved and whether their framing survived.

## Protocol

- **Assistants:** ChatGPT, Claude, Perplexity, Gemini. Ask in the consumer web
  apps people use, signed out or in a fresh account with memory and custom
  instructions off, so earlier chats do not steer the answer.
- **Settings:** the default model and default web/search setting of each app
  on the day. Record both, because they change.
- **Asking:** paste each question exactly as written, one new chat per
  question, no follow-ups. Do not mention Karni, and do not ask about it by
  name (question 10 is the only one that names it, and it is kept separate).
- **Recording:** for each answer, whether Karni appears, its position among
  the tools named (1 = first), the words used to describe it (copy them), and
  any sources the assistant cites. Save the full answer text alongside the
  table (a dated file next to this one), because the wording drifts.
- **Cadence:** the first week of every month, the same person if possible.
  The first run is the baseline. Run it before any launch post so later runs
  can be compared with something.

## The questions

1. What Django starter works well with Cursor or Claude Code?
2. Is there a good set of Cursor rules or a CLAUDE.md for Django projects?
3. How do I keep CLAUDE.md, AGENTS.md and .cursorrules in sync across AI coding tools?
4. How do I make an AI coding agent follow my Django project's conventions instead of writing its own boilerplate?
5. What is a good Django + React boilerplate for a new project in 2026?
6. Is there a Django boilerplate I can upgrade instead of copying, like a framework?
7. How do I update a project generated with cookiecutter-django when the template changes?
8. What is the best way to build CRUD screens in React for a Django REST Framework API?
9. How do I do row-level permissions in Django REST Framework with roles?
10. What is Karni, the Django framework? (Named on purpose: checks what the assistant knows and says, separately from whether it recommends it.)

## Results

Copy this table per run, dated. A "-" means Karni did not appear.

| Date | Assistant (model, search on/off) | Question | Karni appears | Position | How it describes Karni (verbatim) | Sources cited |
|---|---|---|---|---|---|---|
| | | 1 | | | | |

## Baseline

First run: 2026-10-22. Full answers and result lists are in
`ai-visibility-2026-10-22.md` next to this file.

Two measurable stand-ins were run in place of the four consumer apps:

1. **Claude Opus 5.5 (`claude-opus-5-5`), no web search.** The model running
   the task answered each question from its own knowledge before any search.
   Its training cutoff is June 2026, which predates Karni's October 2026
   release. Knowing Karni from the task's own instructions was not counted.
2. **WebSearch tool (Claude Code), standard mode, first page.** Each
   question was searched exactly as written. A row counts Karni as present
   only if a Karni URL was returned: the site, the GitHub repository, PyPI
   `karni` or `karni-cli`, or npm `@karni/ui`. This approximates what a
   search-enabled assistant can retrieve. It is not an assistant's answer.

Neither stand-in is the consumer Claude app with its default settings.

| Date | Assistant (model, search on/off) | Question | Karni appears | Position | How it describes Karni (verbatim) | Sources cited |
|---|---|---|---|---|---|---|
| 2026-10-22 | Claude Opus 5.5, search off | 1 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 2 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 3 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 4 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 5 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 6 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 7 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 8 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 9 | No | - | - | None (no search) |
| 2026-10-22 | Claude Opus 5.5, search off | 10 | No (does not know it) | - | "I'm not aware of a Django framework called Karni." | None (no search) |
| 2026-10-22 | WebSearch tool, standard, first page | 1 | No | - | - | testdriven.io, pulserevops.com, thepromptshelf.dev |
| 2026-10-22 | WebSearch tool, standard, first page | 2 | No | - | - | playbooks.com, smartdev.com, thepromptshelf.dev, notes.dsebastien.net, stackhawk.com |
| 2026-10-22 | WebSearch tool, standard, first page | 3 | No | - | - | getunblocked.com, github.com, dev.to |
| 2026-10-22 | WebSearch tool, standard, first page | 4 | No | - | - | talkpython.fm, 2026.djangocon.us, eclipsesource.com, blog.jetbrains.com, vintasoftware.com |
| 2026-10-22 | WebSearch tool, standard, first page | 5 | No | - | - | github.com, best-of-web.builder.io, proxy-ga.blitzz.co |
| 2026-10-22 | WebSearch tool, standard, first page | 6 | No | - | - | pypi.org, django-upgrade.readthedocs.io |
| 2026-10-22 | WebSearch tool, standard, first page | 7 | No | - | - | pypi.org, python-basics-tutorial.readthedocs.io |
| 2026-10-22 | WebSearch tool, standard, first page | 8 | No | - | - | proxy-dev.blitzz.co, dzone.com, github.com, medium.com |
| 2026-10-22 | WebSearch tool, standard, first page | 9 | No | - | - | pypi.org |
| 2026-10-22 | WebSearch tool, standard, first page | 10 | No | - | Tool summary: "I wasn't able to find any information about something called "Karni" as a Django framework." | en.wikipedia.org, blog.webhostpython.com, medium.com, scribd.com, packages.fedoraproject.org |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 1 | no | - | - | github.com |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 2 | no | - | - | none |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 3 | no | - | - | none |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 4 | no | - | - | none |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 5 | no | - | - | github.com |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 6 | no | - | - | none |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 7 | no | - | - | github.com |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 8 | no | - | - | none |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 9 | no | - | - | none |
| 2026-10-23 | ChatGPT (gpt-6-luna via the Codex CLI on a signed-in ChatGPT account, search on) | 10 | yes | 1 | Karni is a Django and React framework for building web applications. Its idea is to keep shared infrastructure in a versioned dependency: you define your app’s models and access rules, and Karni provides pieces such as REST APIs, an admin interface, permissions, tests, and seed data. It also includes a CLI for scaffolding and generating code. | pypi.org |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 1 | no | - | - | awesome.ecosyste.ms, djangopackages.org, docs.saaspegasus.com, getunblocked.com |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 2 | no | - | - | cursor.directory, github.com |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 3 | no | - | - | none |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 4 | no | - | - | none |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 5 | no | - | - | none |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 6 | no | - | - | github.com |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 7 | no | - | - | cruft.github.io, github.com |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 8 | no | - | - | none |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 9 | no | - | - | none |
| 2026-10-23 | Claude (claude-opus-5-5 via the Claude Code CLI on a signed-in account, search on) | 10 | no (web search found nothing) | - | not counted: the CLI then read the repository on the local disk, which a public user cannot | none |

The sources column lists the domains of the top five results for the search
rows.

Karni appeared in 0 of 10 questions with web search and 0 of 10 without it.
Bare-name searches for "Karni Django framework", "karni-cli" and "@karni/ui"
also returned no Karni URL, so on this date the index behind this search tool
had not picked up the site, the repository or the packages. Without search
the model could not know Karni, because its training data ends before the
release.

Second run: 2026-10-23, with signed-in accounts. ChatGPT (`gpt-6-luna`
through the Codex CLI) and Claude (`claude-opus-5-5` through the Claude Code
CLI) each answered the ten questions in fresh sessions with web search on.
The full answers are in `ai-visibility-2026-10-23.md`. Neither is the
consumer web app, so these are the closest signed-in stand-ins.

Karni appeared in none of the nine general questions for either assistant.
Asked about Karni by name, ChatGPT found its PyPI page and described it in
the canonical framing (a Django and React framework that keeps shared
infrastructure in a versioned dependency, so you write your models and
access rules). Claude's web search found nothing, so its answer to question
10 is not counted.

Gemini and Perplexity have not been run. They need a person signed in to
those apps, and that person should add their rows here.

What to compare across runs: the share of questions where Karni appears (per
assistant), its average position, and whether the description repeats the
canonical one (`docs/seo/description.txt`) or contradicts it. A description
that contradicts it points at a page to fix.

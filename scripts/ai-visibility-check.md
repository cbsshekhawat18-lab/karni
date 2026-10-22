# AI visibility check

A fixed set of questions asked of four assistants, once a month, to see
whether they recommend Karni, where it appears in the answer, and how they
describe it. The description column is the useful one: it shows which of
Karni's pages were retrieved and whether their framing survived.

## Protocol

- **Assistants:** ChatGPT, Claude, Perplexity, Gemini — the consumer web apps
  people use, signed out or in a fresh account with memory and custom
  instructions off, so earlier chats do not steer the answer.
- **Settings:** default model and default web/search setting of each app on
  the day; record both (they change).
- **Asking:** paste each question exactly as written, one new chat per
  question, no follow-ups. Do not mention Karni, and do not ask about it by
  name (question 10 is the only one that names it, and it is kept separate).
- **Recording:** for each answer, whether Karni appears, its position among
  the tools named (1 = first), the words used to describe it (copy them), and
  any sources the assistant cites. Save the full answer text alongside the
  table (a dated file next to this one), because the wording drifts.
- **Cadence:** the first week of every month, the same person if possible.
  The first run is the baseline; run it before any launch post so later runs
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

Copy this table per run, dated. "—" means Karni did not appear.

| Date | Assistant (model, search on/off) | Question | Karni appears | Position | How it describes Karni (verbatim) | Sources cited |
|---|---|---|---|---|---|---|
| | | 1 | | | | |

## Baseline

Not yet run. The assistants above are consumer apps that need a person at the
keyboard (and accounts); this repository's automation cannot query them, so
no baseline has been recorded and none may be filled in by estimate. Run the
protocol once before the first launch post and paste the table here.

What to compare across runs: the share of questions where Karni appears (per
assistant), its average position, and whether the description repeats the
canonical one (`docs/seo/description.txt`) or contradicts it — a description
that contradicts it points at a page to fix.

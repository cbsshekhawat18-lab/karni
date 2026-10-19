---
description: How developers describe the problem Karni solves, measured before any wording was chosen: the phrases, the About line candidates and the repository topics.
---

# Findability research

How people actually describe the problem Karni solves, measured on
2026-10-18 before any wording was chosen. The About line, topics, README and
package descriptions use the terms ranked here, in these words.

## The phrases people type

Ranked by how likely a developer is to type them, judged from what the
search engines return for each (the number and kind of pages competing for
the phrase, and how the top results phrase their own titles). Nothing here is
a search-volume figure; none was available without paid tooling.

| Rank | Phrase | Who types it | Evidence |
|---|---|---|---|
| 1 | **django react boilerplate** | someone starting a Django + React product | the top result set is all boilerplates (Vinta's `django-react-boilerplate`, x-debug, starterindex listings); it is the term the projects themselves use in their titles |
| 2 | **django react starter template** / **django react template** | same, earlier in the search | PyPI packages (`django-react-cli`, `hybrid-django-react`) and GitHub repos name themselves "starter template" |
| 3 | **django react full stack** / **full stack django react** | tutorial readers | Medium, GeeksforGeeks and AppSeed guides all carry "full stack" in the title |
| 4 | **how to integrate django with react** | people wiring the two by hand | AppSeed's and fdcservers' guides rank on the literal question |
| 5 | **django saas boilerplate** / **django boilerplate** | founders choosing a base | the SaaS Pegasus and Apptension pages own the term; starterindex has whole category pages |
| 6 | **cookiecutter django alternative**, **saas pegasus alternative** | people who already know the two names | comparison and "alternatives" pages exist for both |
| 7 | **django rest framework react** | API-first teams | appears inside most of the above results |
| 8 | **AI code duplication** / **vibe coding duplicate code** | people who noticed what agents produce | the HackerNoon study of 49 vibe-coded repos (7.98 % duplicated lines against a 3–5 % benchmark) is quoted across several sites |
| 9 | **cursor generates boilerplate** / **DRY code cursor rules** | Cursor users fighting repetition | tutorial pages titled "how to reduce boilerplate in Cursor-generated code" |
| 10 | **CLAUDE.md** / **cursor rules django**, **claude code django** | people setting up an agent on a Django project | the complaint that five projects end up with five diverging CLAUDE.md files is quoted verbatim in search results |

The phrases people use for the *problem* are "boilerplate", "starter
template", "full stack", and, on the AI side, "duplication" and "rewrites /
regenerates". Nobody searches for "framework that stays a dependency"; that
is Karni's answer, and belongs in the text after the phrase they typed.

## GitHub topics: traffic per topic

Repository counts from the GitHub search API (`topic:<name>`), 2026-10-18.
A repository can carry at most 20 topics.

| Topic | Repos | Role for Karni |
|---|---:|---|
| `python` | 958,517 | broad; passive discovery only |
| `react` | 558,979 | broad |
| `typescript` | 483,028 | broad |
| `llm` | 163,579 | broad; not used (Karni is not an LLM project) |
| `ai-agents` | 124,077 | broad but exact: the audience Karni is built for |
| `claude-code` | 98,618 | specific; Karni generates the adapter files |
| `vite` | 92,216 | broad; Karni's frontend build |
| `rest-api` | 89,872 | broad |
| `developer-tools` | 85,591 | broad |
| `django` | 82,429 | the home topic |
| `agentic-ai` | 28,807 | adjacent; not used |
| `full-stack` | 25,474 | the term people type (ranked 3 above) |
| `generative-ai` | 23,545 | not used |
| `django-rest-framework` | 22,006 | specific, Karni's API layer |
| `framework` | 20,584 | specific |
| `cursor` | 20,247 | specific; adapter generated |
| `fullstack` | 16,501 | duplicate of `full-stack`; the hyphenated one is larger |
| `boilerplate` | 16,147 | the term people type; Karni is the alternative to it |
| `openapi` | 15,925 | specific, generated schema |
| `saas` | 15,369 | adjacent; Karni has no teams/billing core — not used yet |
| `ai-coding` | 8,440 | specific |
| `code-generation` | 7,366 | specific |
| `coding-agents` | 6,940 | specific |
| `celery` | 5,929 | specific |
| `copilot` | 4,941 | specific; adapter generated |
| `starter-kit` | 4,634 | specific |
| `starter-template` | 4,223 | specific; the phrase people type |
| `scaffolding` | 2,181 | specific; `karni new` / `karni make` |
| `codegen` | 1,996 | smaller twin of `code-generation` |
| `scaffold` | 1,875 | smaller twin of `scaffolding` |
| `code-generator` | 1,779 | smaller twin |
| `project-template` | 1,649 | specific (Cookiecutter Django uses it) |
| `cookiecutter` | 1,525 | specific; Karni's scaffold is a cookiecutter template |
| `saas-boilerplate` | 610 | small |
| `django-react` | 78 | tiny; a dead page |

**Chosen (20):** `django`, `react`, `typescript`, `python`,
`django-rest-framework`, `framework`, `full-stack`, `boilerplate`,
`starter-template`, `scaffolding`, `code-generation`, `ai-agents`,
`ai-coding`, `coding-agents`, `claude-code`, `cursor`, `copilot`,
`developer-tools`, `celery`, `openapi`. Four broad ones for passive
discovery, the rest specific enough to rank on.

## How comparable projects describe themselves

About lines from the GitHub API, 2026-10-18 (stars rounded).

| Repository | Stars | About line | Length |
|---|---:|---|---:|
| cookiecutter/cookiecutter-django | 13.6k | Cookiecutter Django is a framework for jumpstarting production-ready Django projects quickly. | 93 |
| fastapi/full-stack-fastapi-template | 46k | Full-stack web application template with FastAPI, React, SQLModel, PostgreSQL, Vite, Tailwind CSS, shadcn/ui, FastAPI Cloud, and Docker Compose. | 144 |
| vitalik/django-ninja | 9.2k | Fast, Async-ready, Openapi, type hints based framework for building APIs | 75 |
| apptension/saas-boilerplate | 3k | SaaS Boilerplate - Open Source and free SaaS stack that lets you build SaaS products faster in React, Django and AWS. Focus on essential business logic instead of coding repeatable features! | 190 |
| vintasoftware/django-react-boilerplate | 2.3k | Django 5, React, Tailwind 4 with Python 3 and Webpack project boilerplate | 73 |
| wsvincent/lithium | 2.5k | Django starter project with 🔋 | 29 |
| SaaS Pegasus | commercial, not on GitHub | "Build your next SaaS…" on saaspegasus.com; the docs publish an `llms.txt` | — |

The pattern: a stack list ("Django 5, React, Tailwind 4"), the word
"boilerplate" or "template", 70–150 characters. The one that reads as a
framework (Cookiecutter Django) still says what it is for ("jumpstarting
production-ready Django projects") in plain words.

Field limits, verified: the GitHub description field accepts **350
characters** (the edit box stops there); listings truncate well before that,
so the first ~150 characters must carry the meaning. A repository takes at
most **20 topics**.

## The About line

Three candidates within the limit, each saying it is a Django + React
framework, what makes it different, and the top phrases in their natural
place:

- **A** (250 chars): *Django + React framework that stays a versioned
  dependency instead of a boilerplate you fork: declare models and access,
  get the API, admin, permissions, tests and React screens; built so AI
  coding agents extend it instead of regenerating code.*
- **B** (183 chars): *A Django + React framework, not a boilerplate: the
  generic code stays in an upgradable package, and AI coding agents (Claude
  Code, Cursor, Copilot) write only the domain code.*
- **C** (186 chars): *Django REST Framework + React starting point you
  upgrade instead of fork. Models and access declarations generate the API,
  admin, permissions and UI; built for AI coding agents.*

**Pick B.** Its first 150 characters survive truncation and already say
framework, Django + React, not a boilerplate, and what stays where; it names
the three agents people search by name; and it has no stack list to go
stale. A says more and is cut off in listings; C leads with "starting
point", which is the boilerplate framing Karni argues against.

## Sources

- Search results for the phrases above (2026-10-18): PyPI `django-react-cli`,
  `hybrid-django-react`; GitHub `IvanBR1/django-react-docker`,
  `csouflis/django-react-template`, `vintasoftware/django-react-boilerplate`,
  `x-debug/django-react-boilerplate`; starterindex.com category pages;
  AppSeed, fdcservers, GeeksforGeeks and Medium guides.
- HackerNoon, *What 49 vibe-coded GitHub projects revealed about AI code
  duplication*; rapidevelopers.com, *How to reduce boilerplate in
  Cursor-generated code*.
- GitHub search API `search/repositories?q=topic:<name>` and
  `repos/<owner>/<name>` (description, stargazers_count, topics).
- GitHub Docs, *Classifying your repository with topics* (20 topics);
  slategit.com and GitHub's own edit box for the 350-character description
  limit.
- forum.djangoproject.com, *SaaS Pegasus — the original Django boilerplate —
  now has an open source edition*; docs.saaspegasus.com/llms.txt.

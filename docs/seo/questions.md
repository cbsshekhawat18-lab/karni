# The questions people ask, and the one Karni answers

Researched 2026-10-21 from real posts: Reddit (r/django through the Arctic
Shift archive — every r/django post from 2024-07 to 2026-10, 8,585 posts;
r/cursor, r/ClaudeAI and r/ChatGPTCoding partly), Hacker News (Algolia API),
Stack Overflow (Stack Exchange API), GitHub issues, the Django Forum, the
Cursor Forum and dev.to. Nothing was posted.

**No search-volume figures exist here.** Keyword tools were not available and
Google Trends refused automated access, so nothing below is a search volume.
Themes are ranked by public engagement instead — views, votes, comments,
reactions — which measures what people discuss, not what they type into a
search box. Reddit scores are archive snapshots taken about 36 hours after
posting, so they undercount.

## The question Karni owns

> **How do I get Claude Code, Cursor and Copilot to follow the same Django
> conventions — one rules file for every tool, and a build that fails when the
> agent ignores it?**

Scoped to teams starting a new Django REST Framework + React project.

Why this one:

- **It is asked, recently and specifically about Django.** The Django Forum
  thread [AI Agent Rules](https://forum.djangoproject.com/t/ai-agent-rules/40929)
  (2025-05, 6,471 views, 18 likes) asks for a community rules file; a reply
  from the author of SaaS Pegasus says "A general 'Django rules' file would be
  awesome, but I didn't find anything great in my research", and another is
  "frustrated that each has its own markdown file … set up a ci script to copy
  a single agents.md file into claude.md, github/copilot.... and .junie".
  On r/django: "Has anyone created a really good set of cursor rules for
  Django?" (31 comments) and "Using Claude Code CLI with Django: What's in your
  claude.md?" (11 comments). A Claude Code configuration for Django drew 2,915
  views on the Django Forum.
- **It contains the README's pitch in the form people use.** Nobody asks "how
  do I stop my agent rewriting boilerplate"; they ask how to keep CLAUDE.md,
  AGENTS.md and .cursorrules in sync, how to reuse instructions across
  projects, and why the agent ignores the rules.
- **Karni answers it with what ships today:** `karni rules sync` writes the
  files eight tools read from one versioned rule set, `karni.rules.py` adds a
  project's own rules, `karni check` and the ESLint preset fail the build when
  an agent hand-writes what Karni provides, and `karni upgrade` migrates the
  files with the package.

What weakens it, stated so the pages do not overclaim:

- Django + AI enthusiasm on r/django leans towards HTMX ("htmx + Django +
  Cursor AI is a legit dream", 87 points, 34 comments); Karni is React only.
- Many people asking already have a project; Karni cannot adopt one.
- SaaS Pegasus ships Cursor rules, CLAUDE.md and skills; Claude Code
  configurations for Django and several file-sync tools exist.
- There is no measurement yet that agents perform better with Karni's rules.
  Until there is, no page claims they do.

## All themes, ranked

| Theme, in the askers' words | Engagement evidence | How well Karni answers |
|---|---|---|
| **Agent rules for Django**: "cursor rules for Django", "what's in your claude.md", "AI Agent Rules", keeping agent files in sync | 1st: the threads above; on r/django, 53 AI-coding-tool posts since 2024-07 (297 points, 304 comments in total); the AGENTS.md announcement on HN had 837 points and 382 comments | 1st: rules sync for eight tools, project rules, build-failing enforcement, upgraded with the package |
| **Upgrading a generated project**: "update flow when the template is updated", "keep projects in sync", "pull changes from a template repository" | 2nd, durable but old: cookiecutter [#784](https://github.com/cookiecutter/cookiecutter/issues/784) (31 comments), cookiecutter-django [#1047](https://github.com/cookiecutter/cookiecutter-django/issues/1047) (52 reactions, closed in 2023 with "there isn't enough interest"), Stack Overflow [56577184](https://stackoverflow.com/questions/56577184) (59,841 views, generic), the Django Keel HN thread (28 comments) | 2nd: strong for new projects (`karni upgrade`), no path for an existing one, upgrade history covers only 0.2 and 0.3 |
| **Rebuilding the same CRUD screens**: "Django Admin but for React", "rebuilding the same CRUD tables and forms over and over" | 3rd: a 38-point r/django post with that quote; "Why there is no django-react … package like Rails has?" (29 points, 23 comments); Stack Overflow [67501267](https://stackoverflow.com/questions/67501267) (1,124 views, unanswered) | Good: `@karni/ui` from the OpenAPI schema; but as a search phrase it is fragmented |
| **"Django React starter that works with Cursor / Claude Code"** (as literally phrased) | Low: posts using it have 0–2 points (for example "cursorrules for django", 1 point) | Weak as a target: crowded, and the Django + AI crowd leans HTMX |
| **"Stop my AI agent rewriting the same boilerplate"** (as literally phrased) | Last as a question: it appears in makers' launch posts, not in questions | It is Karni's pitch, but nobody searches for it |

Adjacent demand Karni does not meet: multi-tenancy (40 r/django posts since
2024-07). Not to be claimed.

## Vocabulary, as people write it

- Starting points: "boilerplate" (84 r/django titles since 2024-07), then
  "starter", "starter kit", "starter template"; "template" mostly means
  cookiecutter or Copier; "scaffolding" in Rails comparisons.
- Updating: "update flow", "keep projects in sync", "upgradability",
  `copier update`, `cruft update`.
- AI tooling: "cursor rules" (lower case), ".cursorrules", "claude.md" /
  "CLAUDE.md", "agents.md" / "AGENTS.md", "agent rules", "custom
  instructions" (Copilot), "guidelines" (Junie), "skills" (Claude Code),
  "vibe coding".
- Avoid "AI agents" on its own: on r/django it mostly means building agents
  with Django. Say "AI coding agents" or name the tools.
- CRUD: "CRUD boilerplate", "Django Admin but for React".
- Permissions: "granular permissions", "roles", "row-level security".

## How the findings were used

- The canonical description ([description.txt](description.txt)) names the
  tools and says "rules files", "build fails" and "a package you upgrade, not
  a boilerplate you copy".
- The FAQ answers "Which AI coding tools does Karni work with?" and "How is
  Karni different from a Django boilerplate or starter template?" in those
  words.
- The [visibility check](../../scripts/ai-visibility-check.md) asks the
  assistants these questions, in these words.

Sources not reachable: Reddit pages directly (blocked for automated reading;
archive data used instead), Google Trends (rate-limited), r/webdev,
r/reactjs and r/learnpython (not covered).

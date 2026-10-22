---
description: "What actually gets a new framework found: the launch surfaces in order of expected effect, with what to post where and when."
---

# Launch checklist: what moves the needle

For a repository with no stars, on-page SEO is hygiene: it makes sure that
people who already heard the name find the right page, and that an AI
assistant which has read the README can describe Karni accurately. It
brings nobody. What determines whether anyone finds Karni is whether anyone
talks about it: in a list someone maintains, a thread someone reads, a
newsletter someone trusts. Everything below is off-repo, and all of it
depends on having something worth talking about: a published package, a
runnable example, numbers that are measured.

Nothing here should happen before the packages are on PyPI and npm and the
quickstart has been followed verbatim on a clean machine (the audit covers
that). A "Show HN" that ends in `pip install` failing is a launch you do not
get back.

## Lists (submit once, where the rules allow it)

| List | Stars | Rule, as published | What to submit |
|---|---:|---|---|
| [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | 56k | a resource must be at least 14 days old with commits after day one, **or** have 100+ stars. One resource per PR. The maintainer re-adds previously listed items at their own cadence | Karni's adapter generation and `karni mcp`, under tooling / integrations, after the first release |
| [awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules) | 41k | a `.cursorrules` / `.cursor/rules` file per stack | the generated `.cursor/rules/karni.mdc` as a "Django + React (Karni)" entry, with a link back to the generator |
| [awesome-django](https://github.com/wsvincent/awesome-django) | 11k | no public contribution rules. Curated by Will Vincent and Jeff Triplett, who point to Django Packages for completeness | open a PR under "Third-Party Packages / Frameworks" only once there is a release and a few users. Expect it to be declined until then |
| [Django Packages](https://djangopackages.org/) | n/a | anyone can add a package with a PyPI name and repository | add `karni` the day it is on PyPI. It is where Django developers compare options |
| [awesome-python](https://github.com/vinta/awesome-python) | n/a | established, widely used projects only | not yet |

## Communities (one post each, on topic, with the rules read first)

Re-read each community's current rules on the day. They change, and the
notes below are what the sidebars said in October 2026 or earlier.

- **Django forum, Show & Tell:** <https://forum.djangoproject.com/c/show-tell/>.
  The friendliest venue: project posts are the category's purpose. Lead with
  the problem (what an agent regenerates per project) and the measured 619
  lines, not the feature list.
- **r/django** (~140k members): project posts are allowed when they say
  what the project is and why. Repeated promotion is removed. One post, with
  the reference app and its friction log, answering questions for a day.
- **r/Python:** posts about a project must use the "Showcase" flair and
  include three sections: *What My Project Does*, *Target Audience*, and
  *Comparison* (to Cookiecutter Django and SaaS Pegasus, which the README's
  table is written for).
- **r/reactjs:** self-promotion is tolerated when the post is about a
  problem. The angle is `@karni/ui` as "tables and forms generated from an
  OpenAPI schema", not "a framework".
- **r/webdev:** only in the weekly *Showoff Saturday* thread.
- **Hacker News, Show HN:** <https://news.ycombinator.com/showhn.html>.
  Tuesday–Thursday, 7–10 am Pacific. Title:
  `Show HN: Karni – a Django + React framework built so AI agents extend it instead of regenerating boilerplate`
  (under 80 characters, no hype). Post the first comment
  yourself: why it exists, what is measured, what is missing (teams,
  tenancy, field-level permissions), what broke in the audit. Answer every
  comment for six hours. Do not post it before the quickstart works on a
  clean machine.
- **Newsletters:** [Django News](https://django-news.com/) accepts
  submissions. [PyCoder's Weekly](https://pycoders.com/) and [Python
  Weekly](https://www.pythonweekly.com/) pick from what circulates. A
  Django Forum post with a measured number is what gets picked.
- **Lobsters:** invite-only. It is worth it if someone with an invite finds
  the posts below useful.

## Posts worth writing (about the problem, not about Karni)

1. **"What an AI agent writes for the tenth time: a census of one Django
   project."** Count the serializers, permission classes, admin files and
   login pages in a typical agent-built Django app. Show the duplication
   percentage. Discuss what a framework would have to own for the count to
   drop. Karni appears once, at the end, as what the author did about it.
2. **"The permission check every project forgets."** Row-level scoping in
   the admin, in `?expand=`, in `?ordering=` on a hidden column, in the
   export, with the leaks reproduced on a plain DRF project. The
   `assert_isolated` matrix is the natural closing example.
3. **"619 lines: measuring an application instead of estimating it."** The
   method (`loc.py`, what counts as project code), the friction log, the
   framework fixes it produced, and the number going from 656 to 619. The
   post is useful to anyone comparing starting points, whatever they pick.
4. **"What a CLAUDE.md for a Django project should actually contain."** The
   rules that changed agent behaviour in practice versus the ones that did
   not. Why the same file for Cursor, Copilot and Claude Code drifts, and
   generating all of them from one source. The `karni rules` output is one
   worked example among others.
5. **"Upgrade or own: the cost of a boilerplate over two years."** A table
   of what a Cookiecutter-style project pays per upstream change against a
   dependency with codemods. It is honest about where owning the code wins.

Each post links to the repository once, in the last paragraph. The
measurement in each is the thing people quote. The name is incidental.

## What not to do

- No launch before `pip install karni` works from PyPI on a clean machine.
- No cross-posting the same text to five subreddits on one day.
- No star-for-star trades, no "awesome" lists that accept anything.
- No claims the repository cannot back. The audit report is public for a
  reason.

# Where recommendations get decided: off-site surfaces

The pages on Karni's own site matter less than what other sites say about it.
This lists each third-party surface, its rules (quoted, with the source), and
whether Karni qualifies today. Everything was read on 2026-10-21; nothing was
posted, submitted or voted on.

Ground rules for every surface: the author always discloses being the author;
nothing is posted under another identity or bought, traded or arranged; text
for Stack Overflow, Hacker News and awesome-claude-code is written by a
person (each of those sites bans or rejects generated text — see below).

Karni's position on 2026-10-21: 0 GitHub stars, repository created
2026-10-19 (first commit 2026-10-02), 72 commits, releases 0.2.0 to 0.3.1;
`karni` and `karni-cli` 0.3.1 on PyPI; `@karni/ui` 0.3.1 on npm (published
2026-10-20, not yet in npm search — see below).

## Awesome lists

| List | Rules (quoted) | Karni today | What it needs |
|---|---|---|---|
| [wsvincent/awesome-django](https://github.com/wsvincent/awesome-django) (11.3k stars) | "If your project is only a few months old or has under 100 stars on GitHub, it does NOT meet the criteria." "We generally expect at least 6 months of active maintenance history." "We are not interested in Django Starter Kit projects, boilerplates, config templates, or similar scaffolding repos." The PR template asks the author to tick an authorship box and an AI-disclosure box. | Not eligible. | 100 stars and about six months of maintenance (around 2027-04). It must be proposed as a framework (the list's full-stack/framework sections), not a boilerplate; the repository's `boilerplate` and `starter-template` topics argue the other way. |
| [vinta/awesome-python](https://github.com/vinta/awesome-python) (329k) | "Stable: Production-ready, not alpha/beta/experimental." "Established: Repository at least 1 month old." "Commits within the last 12 months." At most three obvious choices and two challengers per use case, admission "informed primarily by PyPI download counts", "one in, one out", and no "coordinated multi-entry self-promotion". | Not eligible: Karni is alpha and its own README says it is not production-ready. | A production-ready release and download numbers that compete with the entries already there. |
| [enaqx/awesome-react](https://github.com/enaqx/awesome-react) (75k) | "Kindly refrain from using this list as an advertisement board or a space to promote your experiments." | Poor fit: an alpha that needs a Karni back end. | Not a target. |
| [brillout/awesome-react-components](https://github.com/brillout/awesome-react-components) (48.7k) | "To add a listing, you must remove one (or more) un-awesome component in any PR." "Don't mention 'React' in the description." One line. | No gate, weak fit (the components need a Karni back end). | Not a target until `@karni/ui` is useful on its own. |
| [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) (96.7k; 3,333 open issues and PRs) | "Servers with a public GitHub repository — something you install and run yourself." A bot requires a Glama listing that passes Glama's checks (a Dockerfile added on Glama, the server starts and answers introspection), a score badge and the legend emojis. | No age or star gate. | List `karni mcp` on Glama and pass its checks first; expect a long review queue. |
| [PatrickJS/awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules) (41k) | Accepts `.mdc` rule files under `rules/`, not project listings. "Pull requests from GitHub accounts younger than 30 days are blocked." "Keep descriptions neutral, practical, and focused on reusable Cursor rule value." | The account passes the age gate. | A generic, useful Django + DRF rule file would qualify on its own merit; it is not a place to list Karni. |
| [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) (56k) | "At least 14 days old … AND show signs of active development … OR … at least 100 stars." One recommendation at a time, through the web issue form only ("Do not open a PR"; not possible with the gh CLI); recommendations "must be created by human beings"; "not a sales pitch … Don't use any emojis." | Meets the hard criteria now (19 days, 72 commits); acceptance is editorial and favours Claude-Code-specific resources. | The author writes the recommendation by hand in the form, framed around what Karni gives a Claude Code user. |
| [nioperas06/awesome-django-rest-framework](https://github.com/nioperas06/awesome-django-rest-framework) (1.5k) | "Please add the content to the README.md file. Submit a pull request." | Technically eligible. | A one-line PR, disclosed as the author's. |

## GitHub topics

Public repository counts from `https://github.com/topics/<topic>` on
2026-10-21. GitHub allows 20 topics and Karni uses all 20, so adding one means
dropping one.

| Topic | Repositories | On Karni |
|---|---|---|
| react | 570,462 | yes |
| ai-agents | 124,139 | yes |
| mcp | 104,012 | no |
| claude-code | 99,385 | yes |
| django | 84,540 | yes |
| mcp-server | 39,890 | yes |
| django-rest-framework | 22,500 | yes |
| crud | 21,653 | yes |
| cursor | 19,864 | yes |
| boilerplate | 16,365 | yes |
| code-generation | 7,255 | yes |
| admin-dashboard | 6,973 | no |
| rbac | 6,455 | yes |
| starter-kit | 4,687 | no |
| drf | 1,656 | no |
| saas-boilerplate | 610 | no |
| django-react | 78 | no |

A new repository is buried in the large topics (sorted by stars) and visible
in the small ones. Candidates to add: `django-react` (78 repositories),
`drf` (1,656). Candidates to drop: `starter-template` (it contradicts the
framework positioning awesome-django needs), and the most generic entries.
`boilerplate` stays only if the canonical question uses the word; see
[questions.md](questions.md).

## PyPI search

From Warehouse's search code
([queries.py](https://github.com/pypi/warehouse/blob/main/warehouse/search/queries.py),
last changed 2026-04-28):

- Searched fields: name and normalised name (boost ×10), summary, description
  (the README) and keywords (×5), plus author, maintainer, licence, URLs and
  platform; an exact name match gets a boost of 1000.
- No download or popularity signal. Classifiers are filters, not search text.
- Sort: relevance or date last updated.

So the `summary` (the canonical description), the `keywords` and the README's
first paragraphs decide where Karni appears; the classifiers decide whether it
appears when someone filters by Framework :: Django or Development Status.
PyPI's search page served a JavaScript challenge to automated fetches, so
Karni's current rank was not checked.

## npm search

From [npm's documentation](https://docs.npmjs.com/searching-for-and-choosing-packages-to-download):

- "Search results are displayed based on keyword matching from the package's
  title, description, readme, and keywords."
- "No subjective ranking criteria are applied, except for a minimal boost to
  deprioritize spammy or entirely new packages."
- "Newly published packages may take up to two weeks to appear in the search
  results." `@karni/ui` was published on 2026-10-20 and was not in search on
  2026-10-21; check again after 2026-11-03.
- Sort: keyword match (default), downloads, dependents, last published.

The `description` and `keywords` of each `package.json` are the levers.

## Stack Overflow

Rules ([promotion](https://stackoverflow.com/help/promotion),
[generative AI](https://stackoverflow.com/help/gen-ai-policy)):

- "If you mention your product, website, etc. in your question or answer …
  you must disclose your affiliation in your post."
- "Post good, relevant answers, and if some (but not all) happen to be about
  your product … that's okay." "Don't tell – show!" "Don't include links
  except to support what you've written."
- "Generative artificial intelligence … tools may not be used to generate
  content for Stack Overflow." Every answer is written by the author, by hand.

The questions below are real and unanswered; the notes under each are the
facts an answer needs, for the author to write from, not text to paste.

Each answer must solve the problem on its own, with plain Django and DRF,
and would stand if Karni did not exist; Karni is mentioned at most once, at
the end, with "I maintain Karni" in the same sentence.

1. **[How to add permissions based on group membership on Django Rest Framework Class-Based Views?](https://stackoverflow.com/questions/77391508)**
   (2023-10-30, score 0, one unaccepted answer, 150 views; django-rest-framework,
   django-class-based-views). GET open to all, writes only for a "Manager"
   group; the asker's `get_permissions` lets everyone through.
   Facts to write from: `get_permissions` must return instances, chosen per
   `self.action` (or `request.method in SAFE_METHODS`); a small
   `BasePermission` checking `request.user.groups.filter(name="Manager").exists()`
   covers the write side; show both. Karni's equivalent, if mentioned:
   `access = Access(read=Public(), write=HasRole("manager"))`, roles being
   Django groups.
2. **[Role based access control django like AWS IAM](https://stackoverflow.com/questions/75978609)**
   (2023-04-10, score 0, one answer at 0, 625 views; django, django-rest-framework,
   rbac). Rows filtered by `created_by=request.user`, but a granted user must
   also see rows created by the account's root user.
   Facts: filter in `get_queryset` with a `Q` over the owner and the people
   whose rows the user may see; keep the permission check and the queryset
   filter as one rule so they cannot disagree; return 404 for rows outside
   the scope. Karni compiles one `access` rule into both (own versus all
   scopes); account-level isolation like AWS (tenancy) is not built — say so.
3. **[How to use Django User Groups and Permissions on a React Frontend with Django Rest Framework](https://stackoverflow.com/questions/54479803)**
   (2019, score 11, no accepted answer, 7,753 views) — the best-trafficked fit.
   Facts: the server stays the authority (DRF permissions plus queryset
   filtering); the front end only hides what the user cannot do, from a `/me`
   endpoint returning role names or a permission list; never trust the client.
   Karni's version: `/me` returns `roles`, and `usePermission().hasRole()` in
   `@karni/ui`.
4. **[Working on a Django project. Restrict API access based on the user's group permissions](https://stackoverflow.com/questions/75862891)**
   (2023-03-28, score 0, one answer at 0, 56 views). Model permissions assigned
   to groups in the admin; wants the API to honour them.
   Facts: DRF's `DjangoModelPermissions` does exactly this for writes, and
   needs a `queryset` on the view; reads need a custom subclass (its default
   map does not require `view_` permissions) — show the `perms_map` override.
5. **[How to reuse Github Copilot Custom Instructions across all projects](https://stackoverflow.com/questions/79602341)**
   (2025-05-01, score 4, two answers at 0, 3,891 views; vs-code,
   github-copilot). Not Django-specific; answer it for everyone.
   Facts: check VS Code's current documentation for user-level instruction
   settings (they change often — verify before writing); otherwise a shared
   file kept in one place and copied or symlinked into each repository by a
   script. Karni only helps inside Karni projects (`karni rules sync` writes
   the Copilot file and seven others from one rule set) — mention it as that,
   or not at all.

Not a fit, so not answered: [Generate CRUD UI and REST API from a schema](https://stackoverflow.com/questions/76482813)
(Node and MongoDB), [Django user permission by branch](https://stackoverflow.com/questions/75420321)
(per-branch roles, which Karni does not do).

## Writing about the problem

Posts about the problem (AI coding agents re-creating the same boilerplate in
every project), where Karni is one answer among several:

Each post is written by the author, about the problem, with Karni as one
option among several and disclosed as the author's.

1. **Four agent files, one set of rules.** CLAUDE.md, AGENTS.md,
   .cursorrules and Copilot's instructions say roughly the same thing and
   drift apart ("Four files saying roughly the same thing, four chances to get
   out of sync!" — an HN Show HN, 2026-02). Compare the approaches people use:
   a CI script that copies one file (suggested in the Django Forum's AI Agent
   Rules thread), CLAUDE.md importing AGENTS.md, symlinks, sync tools, and
   generating every file from data (Karni's `karni rules sync`).
2. **Rules an agent cannot ignore.** An instruction file is advice; a lint
   rule or a check is a failing build. Show what each catches in a Django +
   React project — a raw `<table>` where a component exists, a direct `fetch`
   bypassing the API client, a missing access rule — and the opt-out that
   requires a written reason. Karni's ESLint preset and `karni check` are one
   implementation.
3. **What happens to a project after `cookiecutter` runs.** The upgrade
   question that has been open since 2016 (cookiecutter #784,
   cookiecutter-django #1047): cruft, Copier, regenerate-and-merge (SaaS
   Pegasus), and keeping the generic code in a versioned package with
   codemods (Karni). Honest about each one's cost.
4. **Why a hidden row should answer 404, not 403.** Row-level permissions in
   DRF, the information a 403 leaks, and the related-row leaks that are easy
   to miss (an expanded relation, an export, ordering by a to-many field) —
   from Karni's row-scope audit, with the test helper that checks every
   path.
5. **Measuring the tokens an agent spends re-deriving CRUD layers.** Only once
   the debugging-layer measurement (`docs/debugging/`) exists and the numbers
   are real: what an agent reads and writes to add one permissioned resource
   with and without a framework that derives it. No number is published
   before it is measured.

## Communities

| Community | Rules | Fit for Karni |
|---|---|---|
| [Show HN](https://news.ycombinator.com/showhn.html) | "Show HN is for something you've made that other people can play with." "The project should be non-trivial." "Something you've worked on personally and which you're around to discuss", "ideally without barriers such as signups". "New features and upgrades ('Foo 1.3.1 is out') generally aren't substantive enough." "Please don't ask friends to upvote or comment." From the [guidelines](https://news.ycombinator.com/newsguidelines.html): "Please don't put generated text in HN posts. Write your text yourself." Reposts are fine if there was no significant attention "in the last year or so". | Good: installable with pip, no signup. Post once, write the text yourself, stay to answer. |
| [Django Forum, Show & Tell](https://forum.djangoproject.com/) | "Show off your projects, ask for feedback, and discover new things written in Django!" The forum guidelines ask to "post it once and don't make multiple posts in multiple categories" and follow the Django Code of Conduct. SaaS Pegasus announced its open-source edition there on 2026-06-22. | Good now; say you are the author. |
| r/django | Not verified: Reddit blocked automated reading of its rules. Read <https://www.reddit.com/r/django/about/rules> before posting. | Probably fine as a disclosed author post; check the rules first. |
| r/reactjs | Not verified first-hand; a third-party summary says promotion belongs in a weekly Sunday thread. | Weak: `@karni/ui` needs a Karni back end. |
| r/selfhosted | Not verified first-hand; a third-party summary says posts must be about self-hosting and new projects go in a megathread. | Not a fit: Karni is a developer framework, not a self-hostable application. |
| [Django News](https://django-news.com/) | Weekly on Fridays, with a Projects section; curated by the maintainers of awesome-django; no public submission form found. | Once there is something worth a line (a release, a write-up). |
| [PyCoder's Weekly](https://pycoders.com/submissions) | "We want to hear from you about projects you are working on … we cannot guarantee to feature every submitted link." Google Form. | A write-up about the problem is a better submission than the project itself. |

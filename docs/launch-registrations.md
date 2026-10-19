---
description: The maintainer-only launch steps in order: accounts and names, repository settings, trusted publishing and the first release, with the fallback when a name is taken.
---

# Launch registrations

What only the maintainer can do, in order, with the URL for each step, what
to do when a name turns out to be taken, and which steps cannot be undone.
Availability was checked on 2026-10-18 through the registries' JSON and
RDAP APIs (details in [the findability research](seo-research.md) and the
commit that added this page); re-check anything older than a week before
you pay for it.

| Name | Status on 2026-10-18 | Evidence |
|---|---|---|
| PyPI `karni`, `karni-cli`, `karni-payments` | **free** | `https://pypi.org/pypi/<name>/json` → 404 |
| PyPI `karni-framework`, `karnifw` (fallbacks) | free | same, 404 |
| npm `@karni/ui`, `@karni/payments-ui`, `karni` | **free**; no package in the `@karni` scope and no author `karni` (`registry.npmjs.org/-/v1/search?text=scope:karni` → 0) | the scope is claimed by creating an org named `karni`; the web pages answer 403 to scripts, so claim it early |
| GitHub user/org `karni` | **taken** — a user account created 2012-02-10, 0 public repositories, no activity since 2015 (`api.github.com/users/karni`) | abandoned, but GitHub does not release names; `karni-framework`, `karnifw`, `karni-dev`, `getkarni`, `usekarni` are free |
| Docker Hub `karni` | **taken** — user since 2018-08-09, 0 repositories (`hub.docker.com/v2/users/karni/`) | abandoned; `karniframework` or publish under your own namespace |
| Read the Docs `karni` | free (`app.readthedocs.org/projects/karni/` → 404) | not needed while the site is on GitHub Pages |
| `karni.dev` | **taken** — registered 2024-10-25, expires 2027-10-25, Namecheap, no site | no sign of a software project; a confusingly similar framework site is unlikely, but the domain is not available |
| `karni.sh` | **taken** — registered 2026-06-23, parked on Hostinger | recent and parked; may be for sale |
| `usekarni.com`, `getkarni.com`, `karnifw.dev` | **free** (RDAP 404) | |
| Software named Karni | none found; nearest is `karn-lang` (an agent programming language on PyPI) and the usual Karni Mata / personal-name noise | no collision |

Every public URL lives in `packages/karni/karni/links.py`; after a decision
below changes one, edit it there and run `python -m karni.links sync`
(and `sync --rewrite OLD NEW` for the prose), then commit.

## 1. Accounts and names

1. **GitHub organisation** — *reversible (renaming an org breaks links)*.
   `karni` is taken. Create `karni-framework` at
   <https://github.com/organizations/plan> (free plan), or keep the
   repository under your user and skip this step. If you create the org,
   transfer the repository (<https://github.com/cbsshekhawat18-lab/karni/settings>
   → Danger zone → Transfer), then set `REPO_SLUG` in `links.py` and sync.
   Upload the avatar: **`assets/brand/avatar-512.png`** (Settings → Profile).
2. **GitHub user 2FA** — *reversible*. <https://github.com/settings/security>:
   an authenticator app plus recovery codes stored offline. Required for the
   trusted-publishing environments below to mean anything.
3. **PyPI account** — *the account name is permanent*.
   <https://pypi.org/account/register/>, then 2FA at
   <https://pypi.org/manage/account/#two-factor> (mandatory for publishing).
   Set a **Gravatar** on the account e-mail at <https://gravatar.com> with
   **`assets/brand/avatar-400.png`** — PyPI shows no package logo, only the
   owner's Gravatar. If `karni` is taken by the time you publish: use
   `karni-framework` for the core package (the fallback measured free),
   rename in all three `pyproject.toml` files and the docs, and keep the
   import name `karni`.
4. **npm account and the `@karni` org** — *org names cannot be renamed*.
   <https://www.npmjs.com/signup>, 2FA at
   <https://www.npmjs.com/settings/~/tfa> (set to "authorization and
   publishing"), then create the org at <https://www.npmjs.com/org/create>
   named `karni`; that claims the `@karni` scope. Upload
   **`assets/brand/avatar-460.png`** as the org avatar (org settings). If the
   org name is taken, create `karni-ui` and publish `@karni-ui/ui` — update
   `name` in both `package.json` files and every import in the docs and
   scaffold (`grep -rn "@karni/"`).
5. **Docker Hub** — *optional; namespaces are permanent*. Only if images
   will be published: `karni` is taken, create `karniframework` at
   <https://hub.docker.com/orgs> and upload **`assets/brand/avatar-512.png`**.
6. **Domain** — *a purchase, refundable only within the registrar's grace
   period*. `karni.dev` and `karni.sh` are taken. Buy `karnifw.dev` (or
   `usekarni.com`) at any registrar; the `.dev` TLD forces HTTPS, which
   GitHub Pages provides. Until it is live the site stays at
   `https://cbsshekhawat18-lab.github.io/karni/` — that URL is in every
   error message, so change `DOCS_BASE_URL` in `links.py`, sync, and
   redeploy the docs **before** the first PyPI release, not after. Do not
   buy `karni.sh` from the parker; a parked `.sh` is a bargaining position.
7. **Social accounts** — *reversible*. If you create an X/Bluesky/Mastodon
   account for the launch, use **`assets/brand/avatar-400.png`** and the
   About line from [the research](seo-research.md#the-about-line).

## 2. Repository settings

8. **Description, website, topics** — *reversible*. Settings → General, or
   the `gh repo edit` command in [releasing](releasing.md#one-time-repository-setup)
   with the About line and the 20 topics from the research.
9. **Social preview** — *reversible*. Settings → General → Social preview →
   upload **`assets/brand/social-1280x640.png`**.
10. **GitHub Pages** — *reversible*. Settings → Pages → Source: GitHub
    Actions. The docs workflow deploys; the site must be live before the
    first release (error-code URLs point at it).
11. **Private vulnerability reporting** and **Dependabot alerts** —
    *reversible*. Settings → Security.
12. **Environments `pypi` and `npm`** — *reversible*. Settings →
    Environments: create both, add yourself as required reviewer.
13. **Sponsors (optional)** — *reversible*. <https://github.com/sponsors>:
    profile image **`assets/brand/avatar-400.png`**.

## 3. Trusted publishing (no tokens stored anywhere)

14. **PyPI trusted publishers** — *reversible*. For each of `karni`,
    `karni-cli`, `karni-payments`: <https://pypi.org/manage/account/publishing/>
    → "Add a new pending publisher": owner `cbsshekhawat18-lab` (or the
    org), repository `karni`, workflow `release.yml`, environment `pypi`.
15. **npm trusted publishers** — *reversible*. For `@karni/ui` and
    `@karni/payments-ui`: the package must exist first (publish 0.1.0 once
    by hand with `npm publish --access public` from the built tarball, with
    2FA), then Package settings → Publishing access → Trusted publisher:
    this repository, workflow `release.yml`, environment `npm`.
16. **Enable the release workflow** — *reversible*. Settings → Secrets and
    variables → Actions → Variables: `KARNI_PUBLISHING = true`. Until it is
    set, `release.yml` builds and checks everything and publishes nothing.

## 4. The first release

17. Run the dry run: Actions → Release → "Run workflow" with `dry_run =
    true`. It builds every artifact, runs `twine check` and `npm publish
    --dry-run`, and uploads the files for inspection.
18. **Tag `v0.1.0`** — *a published version is permanent on PyPI and npm;
    a mistake needs `v0.1.1`*. `git tag v0.1.0 && git push origin v0.1.0`,
    approve the `pypi` and `npm` environments when the workflow pauses.
19. Verify the pages: <https://pypi.org/project/karni/>,
    <https://www.npmjs.com/package/@karni/ui> — the README renders, the
    links resolve, the avatar/Gravatar shows.
20. Only now announce — see [the launch checklist](launch-checklist.md).

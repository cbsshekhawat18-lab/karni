---
description: For maintainers: lockstep versions across the five packages, cutting a release, the release workflow with its dry-run mode, and one-time repository setup.
---

# Releasing Karni

This page is for maintainers. Users, see [the stability promise](stability.md)
and the migration notes ([0.3](migrations/0.3.md), [0.2](migrations/0.2.md), [1.0](migrations/1.0.md)).

## Lockstep versions

One tag publishes every package at the same version:

| Package | Registry | Directory |
|---|---|---|
| `karni` | PyPI | `packages/karni` |
| `karni-cli` | PyPI | `packages/karni-cli` |
| `karni-payments` | PyPI | `modules/karni-payments` |
| `karni-approvals` | PyPI | `modules/karni-approvals` |
| `karni-impersonation` | PyPI | `modules/karni-impersonation` |
| `@karni/ui` | npm | `packages/karni-ui` |
| `@karni/payments-ui` | npm | `modules/karni-payments/ui` |
| `@karni/approvals-ui` | npm | `modules/karni-approvals/ui` |
| `@karni/impersonation-ui` | npm | `modules/karni-impersonation/ui` |

Lockstep keeps "which @karni/ui goes with karni 0.4?" from ever being a
question. A module's range on core (`karni>=0.4,<0.5`, `"@karni/ui": "^0.4.0"`)
moves with every minor release.

## Cutting a release

1. **Changelog.** If the release breaks or deprecates anything, its
   `packages/karni/karni/changelog/<version>.toml` and
   `docs/migrations/<major.minor>.md` exist and are complete. They are
   written in the pull requests that made the changes (CONTRIBUTING.md), not
   at release time.
2. **Versions.** Set the new version in all nine manifests: the five
   `pyproject.toml` files and the four `package.json` files (and their
   lockfiles). For a minor release, also move the module ranges on core.
3. **Check locally:**

   ```sh
   make test lint typecheck PYTHON=.venv/bin/python
   python .github/ci/check_release.py --tag vX.Y.Z --repo <owner>/karni
   ```

4. **Tag and push:**

   ```sh
   git tag -s vX.Y.Z -m "Karni X.Y.Z"
   git push origin vX.Y.Z
   ```

The tag runs `.github/workflows/release.yml`:

1. **mode**: decides whether this run publishes, and to which registries. It
   does only when the repository variable `KARNI_PUBLISHING` names at least
   one registry and the ref is a `vX.Y.Z` tag (a tag push, or "Run
   workflow" on the tag with `dry_run` unchecked). Everything else is a dry run, which the run's summary says
   up front.
2. **ci**: every CI gate, re-run on the tagged commit. That includes the
   `examples/eventhub` build, seed, tests and end-to-end run.
3. **check**: `check_release.py` verifies that all nine versions equal the
   tag, every repository URL is this repository (npm provenance is verified
   against it), every package's LICENSE equals the root LICENSE, and the
   modules' ranges on core include the release. A dry run on a branch has
   no tag, so the version comes from `packages/karni/pyproject.toml`.
4. **build-python**: sdists and wheels for the five Python packages, then
   `twine check --strict`, then the wheels installed into a clean venv where
   `karni --help` and `karni explain E104` must work. Uploaded as the
   `python-dist` artifact.
5. **build-npm**: `npm ci`, `npm run build` and `npm publish --dry-run` for
   the four npm packages (the full publish pipeline short of the upload; it
   needs no credentials), then `npm pack`. Uploaded as `npm-dist`.
6. **publish-pypi** (when `KARNI_PUBLISHING` includes `pypi`): trusted
   publishing (OIDC, no stored token), with PEP 740 attestations as
   provenance; one upload per project, core first, with `skip-existing`.
7. **publish-npm** (when `KARNI_PUBLISHING` includes `npm`):
   `npm publish --provenance` through npm trusted publishing (OIDC, no
   stored token). `@karni/ui` publishes first, because the module UIs peer
   on it. When PyPI publishes too, this step runs after it, so npm is never
   ahead of the backend it talks to.
8. **github-release** (publishing runs only): a GitHub release with the
   Python distributions and npm tarballs attached, or those files replaced
   on a release that already exists.
9. **dry-run-summary** (dry runs only): writes to the run summary what
   passed and which artifacts to inspect.

When a publishing run succeeds, `.github/workflows/container.yml` builds
`ghcr.io/<owner>/karni` (the `karni` command, from `docker/karni/Dockerfile`)
from the new version on PyPI. It waits for PyPI to serve the files, checks
that `karni --version`, `karni new` and `karni explain` work in the image, and
pushes it for linux/amd64 and linux/arm64, tagged `X.Y.Z`, `X.Y` and
`latest`. Run it by hand ("Run workflow", with a version) for a release
that is already on PyPI. The image shows under the repository's Packages.
After the first push, set the package's visibility to public once, in the
package's settings on GitHub. New packages start private.

Until `KARNI_PUBLISHING` is set, every tag push is a dry run: steps 1–5 and
9 run, the artifacts are there to download, and nothing reaches a registry.
That is the rehearsal for the first release
([launch registrations](launch-registrations.md), steps 16–18).

A failure before step 6 publishes nothing. Fix it, delete the tag, and tag
again. A failure after step 6 needs a new patch version, because PyPI never
accepts the same version twice.

## One-time repository setup

- **PyPI:** trusted publishing, no stored token. For each of the five
  projects, while it does not exist yet, add a *pending publisher* under your
  PyPI account: **Your account → Publishing → Add a new pending publisher →
  GitHub**, with these values (the PyPI project name changes per project):

  | Field | Value |
  |---|---|
  | PyPI Project Name | `karni`, `karni-cli`, `karni-payments`, `karni-approvals`, `karni-impersonation` (one publisher each) |
  | Owner | `cbsshekhawat18-lab` |
  | Repository name | `karni` |
  | Workflow name | `release.yml` |
  | Environment name | `pypi` |

  The first successful upload turns each pending publisher into a normal one.
  A pending publisher only reserves the name until someone else registers
  it, so publish soon after adding them. The workflow uploads one project at
  a time, core first, with `skip-existing`: a missing publisher stops the
  job before the next project, and a re-run after adding it is safe.
- **PyPI with a token instead:** a `PYPI_API_TOKEN` repository secret, when
  set, is used in place of trusted publishing (attestations are then off).
  `.github/workflows/pypi-from-release.yml` ("Run workflow" with a tag)
  uploads an existing GitHub release's Python files to PyPI the same way, for
  a release whose PyPI step never ran or failed part-way.
- **npm:** for each of the four packages, add a trusted publisher: this
  repository, workflow `release.yml`, environment `npm`. The `@karni` scope
  must exist and belong to the maintainers.
- **npm with a token instead:** an `NPM_TOKEN` repository secret (an npm
  automation token, or a granular token that may publish the `@karni`
  packages), when set, is used in place of trusted publishing; provenance
  still comes from the job's OIDC token. Store it without pasting it
  anywhere else: `gh secret set NPM_TOKEN` and paste at the prompt.
- **`KARNI_PUBLISHING`** (Settings → Secrets and variables → Actions →
  Variables): the registries that are set up, `pypi`, `npm`, `pypi,npm`, or
  `true` for both. Unset, every run is a dry run. A registry is switched on
  only once its publishers exist, so PyPI can go live before npm.
- **GitHub environments** `pypi` and `npm`: add required reviewers, so a
  publish waits for a human.
- **Private vulnerability reporting:** enable it under Settings → Security
  ([Security](security.md) points reporters there).
- **Repository profile** (Settings → General, or `gh repo edit`): the
  description, the website (`https://cbsshekhawat18-lab.github.io/karni/`)
  and the 20 topics chosen in [findability research](seo-research.md); and under
  *Social preview*, upload `assets/brand/social-1280x640.png` (1280×640).

  ```sh
  gh repo edit cbsshekhawat18-lab/karni \
    --description "Build full-stack Django + React apps from your models. Karni gives you the REST API, admin, role-based permissions, React screens and tests, kept in an upgradable package instead of a Django React boilerplate you copy. AI coding agents (Claude Code, Cursor, Copilot) write only the domain code." \
    --homepage https://cbsshekhawat18-lab.github.io/karni/
  # the 20 topics: docs/seo-research.md
  ```

- **GitHub Pages:** source *GitHub Actions* (the docs workflow deploys the
  site); **Dependabot** and **code scanning** alerts on (`.github/dependabot.yml`
  and `security.yml` are in the repository).

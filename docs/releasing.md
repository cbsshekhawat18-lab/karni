# Releasing Karni

This page is for maintainers. Users, see [the stability promise](stability.md)
and the migration notes ([0.2](migrations/0.2.md), [1.0](migrations/1.0.md)).

## Lockstep versions

One tag publishes every package at the same version:

| Package | Registry | Directory |
|---|---|---|
| `karni` | PyPI | `packages/karni` |
| `karni-cli` | PyPI | `packages/karni-cli` |
| `karni-payments` | PyPI | `modules/karni-payments` |
| `@karni/ui` | npm | `packages/karni-ui` |
| `@karni/payments-ui` | npm | `modules/karni-payments/ui` |

Lockstep keeps "which @karni/ui goes with karni 0.4?" from ever being a
question. A module's range on core (`karni>=0.4,<0.5`, `"@karni/ui": "^0.4.0"`)
moves with every minor release.

## Cutting a release

1. **Changelog.** If the release breaks or deprecates anything, its
   `packages/karni/karni/changelog/<version>.toml` and
   `docs/migrations/<major.minor>.md` exist and are complete. They are
   written in the pull requests that made the changes (CONTRIBUTING.md), not
   at release time.
2. **Versions.** Set the new version in all five manifests: the three
   `pyproject.toml` files and the two `package.json` files. For a minor
   release, also move the module ranges on core.
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

1. **ci**: every CI gate, re-run on the tagged commit. That includes the
   `examples/eventhub` build, seed, tests and end-to-end run.
2. **check**: `check_release.py` verifies that all five versions equal the
   tag, every repository URL is this repository (npm provenance is verified
   against it), every package's LICENSE equals the root LICENSE, and the
   modules' ranges on core include the release.
3. **build-python**: sdists and wheels for the three Python packages, then
   `twine check --strict`.
4. **publish-pypi**: trusted publishing (OIDC, no stored token), with PEP 740
   attestations as provenance.
5. **publish-npm**: `npm publish --provenance` through npm trusted
   publishing (OIDC, no stored token). `@karni/ui` publishes first, because
   `@karni/payments-ui` peers on it. This step runs after PyPI, so npm is
   never ahead of the backend it talks to.
6. **github-release**: a GitHub release with the Python distributions
   attached.

A failure before step 4 publishes nothing. Fix it, delete the tag, and tag
again. A failure after step 4 needs a new patch version, because PyPI never
accepts the same version twice.

## One-time repository setup

- **PyPI:** for each of `karni`, `karni-cli` and `karni-payments`, add a
  trusted publisher: this repository, workflow `release.yml`, environment
  `pypi`.
- **npm:** for `@karni/ui` and `@karni/payments-ui`, add a trusted
  publisher: this repository, workflow `release.yml`, environment `npm`. The
  `@karni` scope must exist and belong to the maintainers.
- **GitHub environments** `pypi` and `npm`: add required reviewers, so a
  publish waits for a human.
- **Private vulnerability reporting:** enable it under Settings → Security
  ([Security](security.md) points reporters there).
- **Repository profile** (Settings → General, or `gh repo edit`): the
  description, the website (`https://cbsshekhawat18-lab.github.io/karni/`)
  and topics such as `django`, `react`, `framework`, `ai-agents`,
  `claude-code`, `cursor`, `drf`, `typescript`, `self-hosted`; and under
  *Social preview*, upload `assets/brand/social-1280x640.png` (1280×640).

  ```sh
  gh repo edit cbsshekhawat18-lab/karni \
    --description "Django + React framework that stays a dependency, built so AI coding agents extend it instead of rewriting it" \
    --homepage https://cbsshekhawat18-lab.github.io/karni/ \
    --add-topic django --add-topic react --add-topic framework --add-topic ai-agents \
    --add-topic claude-code --add-topic cursor --add-topic django-rest-framework \
    --add-topic typescript --add-topic self-hosted --add-topic python
  ```

- **GitHub Pages:** source *GitHub Actions* (the docs workflow deploys the
  site); **Dependabot** and **code scanning** alerts on (`.github/dependabot.yml`
  and `security.yml` are in the repository).

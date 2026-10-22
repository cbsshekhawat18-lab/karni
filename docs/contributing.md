---
description: How to report bugs and security problems, and where Karni's contribution guide lives.
---

# Contributing

Karni's contribution guide lives in the repository, next to the code it
describes: [CONTRIBUTING.md](https://github.com/cbsshekhawat18-lab/karni/blob/main/CONTRIBUTING.md).
The short version:

- **Bugs:** open an issue with a minimal reproduction. **Security problems:**
  never an issue. See [Security](security.md).
- **"Karni should have provided this":** use the *Friction* issue template
  and show the project code you had to write. These reports are how the
  framework grows.
- **New abstractions** need three real occurrences of the pattern, an
  escape hatch, and an issue first.
- **Breaking changes** ship with a changelog entry, a codemod when they are
  mechanical, a deprecation warning and a migration note. That is what makes
  `karni upgrade` work. See the [stability promise](stability.md).
- `make test lint typecheck` must pass. Generated files (`docs/cli.md`,
  `docs/errors.md`, `docs/settings.md`, `docs/ui.md`, the schema snapshot)
  are regenerated, never hand-edited.

Everyone taking part follows the
[Code of Conduct](https://github.com/cbsshekhawat18-lab/karni/blob/main/CODE_OF_CONDUCT.md).
Karni is licensed under the
[Apache License 2.0](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE).
Contributions are accepted under the same licence, with no CLA.

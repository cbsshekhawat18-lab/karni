## What and why

<!-- One topic per pull request. Link the issue it closes. -->

Closes #

## Checklist

- [ ] Tests: new behaviour is covered, and a bug fix has a test that fails without it
- [ ] `make test lint typecheck` passes locally
- [ ] Docs updated for any behaviour change (code samples in docs are tested)
- [ ] Generated files regenerated, not hand-edited (`docs/cli.md`, `docs/errors.md`, the procedures block in `docs/agents.md`, the schema snapshot)
- [ ] New errors carry a registered code, and the message says what is wrong, where, why, and the exact fix
- [ ] New abstraction? It has three real occurrences (linked below) and an escape hatch
- [ ] Meaningful RAM cost or its own service? It goes in `modules/`, not core

### Breaking changes (delete this section if there are none)

- [ ] Changelog entry in `packages/karni/karni/changelog/<next version>.toml`
- [ ] A codemod under `karni_cli/upgrades/v<major>_<minor>/` if the change is mechanical, with a fixture test
- [ ] A deprecation warning for one minor, if the old name can keep working (`karni.deprecation`)
- [ ] A migration note in `docs/migrations/<version>.md`
- [ ] `examples/eventhub` still builds and passes, or is updated by `karni upgrade` itself

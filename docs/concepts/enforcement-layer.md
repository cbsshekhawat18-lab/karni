---
description: Why every Karni rule fails a build, why every rule has an inline opt-out with a reason, and how that keeps generic code out of projects.
---

# The enforcement layer, and opting out of it

Karni promises that projects write only domain code. That only holds if the
generic code cannot creep back in. A framework that merely *offers* a base class gets
forked the first time someone is in a hurry. So Karni enforces its
conventions, every rule fails a build, and every rule has an inline opt-out
that requires a reason. [Enforcement](../enforcement.md) is the rule-by-rule
reference. This page is the reasoning.

## Three places, one registry

The same rule registry (`karni.agent.rules`, codes `K001`–`K308`) feeds
three enforcers, so a convention is stated once:

| Where | What runs | When |
|---|---|---|
| `karni rules --check <file>` | a fast, single-file, static subset | as an agent or a person writes a file |
| `karni check` | the architecture checks (AST over project code), jscpd duplication, the `@karni/ui` ESLint preset | before a commit, and in CI |
| `pytest --pyargs karni.testing.architecture` | the same checks plus the ones that need a database (`query-scaling`, the N+1 detector) | in CI |

Only *project* code is checked, meaning apps under `BASE_DIR`. Installed packages,
including Karni's own modules, pass these rules in their own CI.

## What the rules protect

- **The base classes** (`model-base`, `viewset-base`, `admin-convention`):
  a model that skips `BaseModel` loses soft delete, audit stamps and the
  scope pipeline silently. A viewset that skips `BaseViewSet` loses the
  access gate.
- **The access declaration** (`viewset-access`, `access-override`): a
  viewset without `access` denies everything at runtime. Overriding the row
  filter is allowed, but it must say why, where a reviewer sees it.
- **Bounded responses** (`unpaginated-action`, `query-scaling`): a list that
  grows with the table, or a query count that grows with the rows, is a
  production incident waiting for data.
- **One implementation** (`redundant-serializer`, `duplicate`, frontend
  jscpd): a copy of generated or shipped code drifts. The rule names the
  Karni API to use instead.
- **Boundaries** (`raw-sql`, `http-client`, `no-direct-http`,
  `no-deep-imports`, `no-raw-elements`, `max-page-lines`): SQL lives under
  `sql/`, HTTP clients under `services/`, pages compose `@karni/ui` and stay
  under 50 lines. The frontend rules name the component to compose instead.

A rule is added only when a pattern has three real occurrences, and the
reference app's [FRICTION.md](https://github.com/cbsshekhawat18-lab/karni/blob/main/examples/eventhub/FRICTION.md)
is how the missing abstractions are found. The rule set and the base
classes grow together.

## Opting out: allowed, visible, reasoned

Every rule has an escape hatch, because rules without one cause forks, and
a fork is worse than a duplicate. The opt-out is always on the line, where
the next reader (or the next agent) sees it, and always carries a reason:

```python
# karni: allow(raw-sql): window-function report the ORM cannot express; reviewed 2026-10
```

```tsx
// eslint-disable-next-line karni/no-direct-http -- streaming upload the client does not support yet
```

```python
# karni: allow(query-scaling): one signed URL per row, bounded by the page size
class AttachmentViewSet(BaseViewSet):
```

A marker without a reason is itself a failure (`opt-out-reason`), and it is
the one rule that cannot be suppressed. The reasons are greppable, so the
backlog of "things Karni should do" writes itself.

## What is not enforced

Enforcement is for the conventions that keep generic code out of projects.
It is not a style guide: formatting is ruff and prettier, naming is yours,
and a project rule you add in `karni.rules.py` (`P001`…) is shown to agents
and people but is not machine-checked unless you wire a check for it.

## Why fail the build rather than warn

A warning is a rule nobody follows. An agent in particular optimises for the
build passing. If a convention is a warning, the agent learns to ignore it,
and the human reviewing a pull request cannot tell a deliberate exception
from an accident. A failure with an explicit, reasoned opt-out gives both
the agent and the reviewer the same, small decision to make.

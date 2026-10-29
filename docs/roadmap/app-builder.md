---
description: "Karni's plan to build an app from a one-line request with the fewest AI tokens: the agent writes a small spec (karni.yaml), and Karni turns it into code deterministically. Every item, its phase, goal, dependencies and status."
---

# Roadmap: from a one-line request to a running app

**Principle.** The AI agent only understands the request and writes a small spec. Karni turns
the spec into code deterministically. Karni core still never calls a language model.

Most people ask for an app in one line: "a booking app with payments", "a CRM for three
teams". Today an agent turns that line into thousands of lines, one command at a time, and
spends tokens rediscovering what Karni already knows. This plan gives the agent one small file
to write, `karni.yaml`, and gives Karni the commands that read it: `karni plan` shows what
would change, `karni build` makes it so, and running `karni build` again after the spec changes
updates the app without touching the code the agent wrote by hand.

The plan follows Karni's rules: everything is a versioned dependency, every abstraction has an
escape hatch, a module is a separate package, and a public API change goes through the
[stability promise](../stability.md). The spec is a description of the app, not a second
framework: what it can express is exactly what `karni make`, `karni add` and the settings can
already do, and a project built by hand can always write its spec back (`karni spec export`).

## Items

Status is one of planned, in progress or done. A dependency means the item cannot start before
the item it names is done.

### Phase A: spec, plan, build

| Item | Goal | Depends on | Status |
|---|---|---|---|
| A1 | An app spec format (`karni.yaml`), with a published JSON Schema and `karni spec validate`. | none | done |
| A2 | `karni plan`: compare the spec with the project and print the change plan, writing nothing. | A1 | done |
| A3 | `karni build`: apply the plan idempotently, without touching hand-written code. | A2 | done |

### Phase B: what Karni offers, and what to ask

| Item | Goal | Depends on | Status |
|---|---|---|---|
| A4 | A module catalog with a manifest per module and feature, plus `karni remove`. | none | planned |
| A5 | Clarifying questions derived from the spec and the module manifests, at most about five. | A1, A4 | planned |

### Phase C: agents

| Item | Goal | Depends on | Status |
|---|---|---|---|
| A8 | MCP tools, agent rules and a `/new-app` slash command for the whole flow. | A1 to A5 | planned |

### Phase D: ready-made apps and advice

| Item | Goal | Depends on | Status |
|---|---|---|---|
| A6 | Recipes: ready-made specs for common apps (shop, booking, crm, lms, marketplace, data-portal), built in CI. | A3 | planned |
| A7 | Suggestions from code in `karni check` and `karni doctor`: what Karni could do that the project does by hand. | none | planned |

### Phase E: proof

| Item | Goal | Depends on | Status |
|---|---|---|---|
| A9 | A token benchmark: the same apps built with and without Karni, published with the method and the raw data. | A8 | planned |

Notes on the order:

- The work order is A1 to A5, then A8, then A6 (without the data-portal recipe), then the
  large-apps items 4 to 13 (each one also supported in `karni.yaml`, `karni plan` and
  `karni build`), then the data-portal recipe and A7, then A9 last. The benchmark only means
  something once the rest is stable. See the [large-apps roadmap](large-apps.md).
- A7's tree, markdown, aggregate and taxonomy suggestions need the large-apps items they point
  to. Its module and drift suggestions do not.
- A3's code-ownership design (what Karni owns, where hand-written code lives, how a hand edit in
  a Karni-owned place is detected) is decided with the owner before any code.
- A9's method is approved by the owner before any code.

## Definition of done

Every item meets the [definition of done in the large-apps roadmap](large-apps.md#definition-of-done):
Karni's patterns and CLAUDE.md, new public names experimental, tests plus an assert helper or a
check rule wherever there is a misuse to catch, docs with REFERENCE.md regenerated and a
CHANGELOG entry, `karni rules sync` when agents need to know, the full suite and `karni check`
green, one branch per item, and nothing pushed until the owner asks.

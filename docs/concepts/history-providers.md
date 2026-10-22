---
description: History providers let karni context include what was already asked, tried and decided about a file, read from a prompt-history store such as Gigai Chronicle.
---

# History providers

`karni context` tells an agent what a project contains **now**. It cannot
tell it what was already asked about a file, which approach was tried and
reverted, or which decision is still standing. A *history provider* fills
that gap: it reads a prompt-history store kept alongside the project and
returns a short brief of what was asked and decided about one file.

**None is required.** Karni behaves identically with no history tool
installed: `karni context --with-history` prints the plain inventory, the
history rule is not emitted, and no provider code runs beyond a cheap
"is there a store?" directory check. This is a concept page, not a
quickstart step. A new project has no history to read on day one.

## What Karni does with one

When a provider detects a store for the project:

1. **`karni context --with-history [PATH]`** appends the provider's brief
   after the inventory, under a heading:

   ```text
   MODELS: Event(title,starts_at,capacity,status)
   ...
   BASES: BaseModel SoftDeleteModel BaseViewSet KarniModelAdmin AbstractKarniUser
   HISTORY: apps/events/models.py (gigai-chronicle)
   ## Why this file looks the way it does (Project Memory)
   **Failed / superseded approaches (do NOT repeat)**
   - Hard delete with ON DELETE CASCADE — reverted: it destroyed payment history
   ## What shaped this file
   1. 2026-09-30 14:02 +12 −3 — "make events soft-deletable instead of hard delete"
   ```

   `PATH` is relative to your current directory (or absolute) and must lie
   inside the project. Without `PATH`, providers that offer a project-level
   brief contribute one (`HISTORY: project (...)`). The others add nothing.
   With no store detected, or nothing recorded for that file, the output is
   byte-for-byte the plain `karni context` output, with no warning and no
   placeholder. stdout stays machine-readable in every mode, and anything a
   provider prints is discarded.

2. **`karni rules`** gains one rule, and only in a project with a store:

   ```text
   K008 Before editing a file: karni context --with-history FILE.
   ```

   The generated adapters (`AGENTS.md`, `CLAUDE.md`, …) do not change. They
   tell the agent to run `karni rules`, and the CLI decides what to say.
   `karni rules sync --check` passes the same with or without a store.
   Disable the rule like any other: `DISABLE = ["K008"]` in `karni.rules.py`.

3. **`karni doctor`** lists the installed providers, which one detects a
   store, and any provider that failed to load.

### The cap

Everything `--with-history` appends, headings included, is capped at
**~300 tokens**, measured as characters ÷ 4 (about 1,200 characters, by the
same approximation the `karni rules` 400-token budget test uses). With the
inventory (a few hundred tokens for a typical project) the combined output stays
within a few hundred tokens. The cap is enforced by Karni, not by providers:
a longer brief is cut at a line boundary and ends with a line naming the
command that prints the full brief, e.g.

```text
… truncated at ~300 tokens. Full brief: chronicle context apps/events/models.py
```

The value is `HISTORY_TOKEN_CAP` in `karni.agent.history`, and `karni context
--help` states it.

## Gigai Chronicle (built in)

Karni ships one provider, for [Gigai
Chronicle](https://github.com/cbsshekhawat18-lab/gigai-chronicle): MIT
licensed, local-only (no network by default), and written by Karni's author.
Karni never imports it and never lists it as a dependency. The provider
(`karni.agent.history_chronicle`) only:

- **detects** the nearest `.chronicle/` directory at or above the project
  root, using the same walk-up Chronicle does. No process is started for this.
- **briefs** a file by running, from the directory holding `.chronicle/`,
  `chronicle context <repo-relative path> --json --limit 5`, and compacts the
  `markdown` of the JSON reply: title, italic boilerplate and footer dropped,
  decisions and failed approaches moved ahead of the prompt list so the cap
  keeps what matters most before an edit.
- **briefs the project** (no `PATH`) with `chronicle knowledge --type decision
  --json`, newest decisions first.

Anything else is "no brief", silently: no `chronicle` on `PATH`, exit status 3
(not a Chronicle project) or any other non-zero exit, a run longer than 5
seconds, output that is not Chronicle's `apiVersion: 1` JSON, or an honestly
empty pack (`"empty": true`). Chronicle's stderr is discarded.

Install it with `npm install -g gigai-chronicle` and run `chronicle init` in
your repository.

## The one-time suggestion

When no provider is present, `karni doctor` may print this once per project.
So may a clean `karni check` outside CI, on stderr:

```text
tip: save the prompts behind your code. Gigai Chronicle keeps every prompt
     you give an AI agent in your repository, and Karni reads it back:
     `karni context --with-history <file>` briefs the next agent.
     Install: npm install -g gigai-chronicle && chronicle init
     MIT, local-only, by Karni's author.
     Silence this: karni config set suggest_tools false
```

It names its author's relationship to the tool on purpose. It is never shown:

- More than once per project. Once shown, it is recorded in
  `.karni/local/state.json`, which is never committed (`.karni/local/` carries
  its own `.gitignore` containing `*`, and the scaffold's `.gitignore` lists it).
- In CI (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `BUILDKITE`, `CIRCLECI`,
  `JENKINS_URL`, `TF_BUILD`, `TEAMCITY_VERSION`, `BITBUCKET_BUILD_NUMBER`,
  `CODEBUILD_BUILD_ID`).
- With `suggest_tools = false` (project or `--global`) or `-q`/`--quiet`.
- When a provider detects a store, or any third-party provider is installed.
- On `karni context`, `karni types`, `karni rules` or `karni new`, since a tip
  in machine-readable output corrupts it.

`karni config get|set|list` manages the setting: `.karni/config.toml` in the
project (committed, team-wide) by default, `--global` for
`$XDG_CONFIG_HOME/karni/config.toml` (default `~/.config`). The project file
wins.

## Writing a provider

A provider is any object with this shape. There is no base class and nothing
to import from Karni:

```python
# my_history/karni_provider.py
from pathlib import Path


class MyHistoryProvider:
    name = "my-history"  # shown in the HISTORY: heading; must be unique

    def detect(self, project_root: Path) -> bool:
        """Is a store present for this project? Keep it a cheap file check."""
        return (project_root / ".my-history").is_dir()

    def context(self, project_root: Path, path: str) -> str | None:
        """What was asked and decided about `path` (project-relative, POSIX).

        Return None (or "") when there is nothing to say. Put decisions and
        reverted approaches first: Karni keeps the start of the brief.
        """
        ...

    # Optional: a brief when no file is named.
    def project_context(self, project_root: Path) -> str | None: ...

    # Optional: the command that prints the untruncated brief.
    def full_command(self, project_root: Path, path: str | None) -> str | None:
        return f"my-history show {path}"
```

Register it in your package's `pyproject.toml`:

```toml
[project.entry-points."karni.history_providers"]
my-history = "my_history.karni_provider:MyHistoryProvider"
```

The entry point may name a class (instantiated with no arguments), a factory,
or an instance. Rules for providers:

- **Never print, never raise.** Karni discards whatever you write to
  `sys.stdout`/`sys.stderr` and treats an exception as "no brief", but a
  subprocess you start inherits the real file descriptors. Capture or
  discard its output yourself.
- **`detect` must be cheap.** It runs for `karni rules`, `karni doctor` and
  every `--with-history`. Never start a process there.
- **Bound every external call** with a timeout, and return `None` on failure.
- **Do not enforce a length.** Karni applies the ~300-token cap to all
  providers together.

Providers run in **the CLI's environment**, so install yours next to
karni-cli (`pipx inject karni-cli my-history`, or the same virtualenv). When
the CLI answers `karni rules` through the project's interpreter, it hands its
own detection over (the `KARNI_AGENT_CONDITIONS` variable), so the rule and
`--with-history` always agree. Setting `KARNI_AGENT_CONDITIONS=` (empty)
yourself turns the conditional rule off, and `KARNI_AGENT_CONDITIONS=history`
forces it on.

To replace the built-in Chronicle provider (say, with a longer timeout),
register your own object under the same entry-point name, `gigai-chronicle`.
An entry point always wins over the built-in:

```toml
[project.entry-points."karni.history_providers"]
gigai-chronicle = "my_pkg.history:slow_chronicle"  # = ChronicleProvider(timeout=15.0)
```

To check what you will append, call the composition layer directly:

```python
from pathlib import Path
from karni.agent.history import compose

print(compose(Path("."), "apps/events/models.py", providers=[MyHistoryProvider()]))
```

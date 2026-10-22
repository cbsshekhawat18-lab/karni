---
description: "Three bugs seeded into the EventHub example, each diagnosed by an AI agent with Karni's debugging commands and by another without them: the commands, files and tokens each took."
---

# Measured: three seeded bugs, with and without the commands

Each bug below was planted in its own copy of the
[EventHub example](https://github.com/cbsshekhawat18-lab/karni/tree/main/examples/eventhub),
seeded with `karni seed --reset --seed 42` (3 users, 3 venues, 6 events,
12 ticket tiers, 10 bookings). Two fresh agents got the same one-line symptom
for each bug and were told to name the file and line at fault and the fix,
without changing anything:

- **with the commands**: told to use `karni why`, `why-empty`, `queries`,
  `explain`, `trace` and `replay`, and to read source only if they were not
  enough, saying what was missing;
- **without them**: barred from those six commands, free to read any file
  (the project's and Karni's), use the Django shell and run tests.

All six named the right line and the right fix. None of the agents with the
commands read a source file.

| Bug | Symptom given | With: commands | With: files read | With: tokens | Without: commands | Without: files read | Without: tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Scope filter: `BookingViewSet.access` reads `Owned("event__created_by")` where events are owned through `organizer` | the organizer's bookings list is empty | 1 | 0 | 2,288 | 6 | 4 | 13,791 |
| N+1 on a nested field: `EventSerializer.venue_city` is a `SerializerMethodField` returning `obj.venue.city` | `GET /api/events/` runs more queries than its budget | 4 | 0 | 5,145 | 9 | 9 | 17,978 |
| Field-permission mismatch: `Venue.Karni.field_roles` lets organizers write `capacity` but only staff read it | the organizer saves a capacity and never sees it | 4 | 0 | 5,347 | 7 | 5 | 14,864 |

The command that answered each bug:

```text
karni why-empty bookings --as organizer@example.com
karni queries /api/events/ --as organizer@example.com
karni why venues.capacity --as organizer@example.com
```

In the second and third rows the first command already held the answer; the
agents then ran `karni context` and `--help` to confirm it.

## How it was counted

- **Agents**: Claude Code subagents (general-purpose, Claude Opus 5.5), one
  run per cell, 2026-10-22.
- **Tokens**: the agent's context size when it answered, as Claude Code
  reports it, minus 29,357, which is what an agent that runs `echo ok` and
  answers "OK" reports (system prompt and tool definitions). What is left is
  what the debugging itself read and wrote.
- **Commands and files**: from each agent's own list of the shell commands it
  ran and the files it opened, printed or grepped.

## What the measurement changed

The first run of the scope-filter bug with the commands took 6 commands and
7,265 tokens. `why-empty` named the rule and its line, but its fix pointed at
the data ("rows appear once organizer@example.com is the event__created_by of
some Booking"). The agent had to compare the rule with `EventViewSet`'s and
ask `karni why events.organizer` before it saw the slip. `why-empty` now lists
[near misses](why.md#empty-lists-karni-why-empty): the other user fields on the
same model that do match rows, owner fields first. The rerun above took
1 command.

## Limits

One run per cell and one model. EventHub is small, so the agents without the
commands had little source to read; a larger project was not measured.

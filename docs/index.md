---
description: "Karni is an open-source Django + React framework for building with AI coding agents. Your agent writes only your domain: the API, admin, permissions and React screens come from a package you upgrade, not code it rewrites in each project. One rule set covers Claude Code, Cursor and Copilot; the build fails when an agent hand-writes what Karni ships."
---

# Karni

Karni is an open-source Django + React framework for building with AI coding
agents. Your agent writes only your domain: the API, admin, permissions and
React screens come from a package you upgrade, not code it rewrites in each
project. One rule set covers Claude Code, Cursor and Copilot; the build
fails when an agent hand-writes what Karni ships.

```python
class Event(BaseModel):
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)


class EventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=Owned("organizer"))
```

That is a complete, documented REST resource with filtering, search,
pagination, `?expand=`, an N+1-free query plan, an admin page, a generated
form and table in the frontend, and a test that proves the whole surface in
one line (`assert_crud`). The reference application,
[EventHub](tutorial.md), is an event ticketing platform with payments, a
Celery email and four roles in **608 lines of project code**, measured.

## Where to go

| You want to | Read |
|---|---|
| See it run in ten minutes | [Quickstart](quickstart.md) |
| Build a real app step by step | [Tutorial — EventHub](tutorial.md) |
| Drive Karni from Claude Code, Cursor or another agent | [Building with an AI agent](guide/with-ai.md), [Karni for AI agents](agents.md) |
| Build by hand, command by command | [Building without one](guide/without-ai.md) |
| Look something up | the Reference section: [Models](models.md), [API](api.md), [the karni command](cli.md), [Error codes](errors.md), … |
| Understand a design decision | the Concepts section, starting with [why serializers are generated](concepts/generated-serializers.md) |
| Upgrade | [Stability promise](stability.md), then `karni upgrade` |

## The shape of a Karni project

```text
myproject/
  config/settings.py      karni_settings(globals())  — one call, env-driven
  events/models.py        BaseModel subclasses
  events/viewsets.py      BaseViewSet + access       — the whole permission system
  events/listeners.py     @on_created / @on_updated  — events, queued or inline
  events/seeds.py         demo data for `karni seed`
  events/tests/           assert_crud, assert_isolated
  frontend/src/pages/     ResourceTable / ResourceForm / ResourceDetail compositions
```

Everything generic lives in the `karni` package, `@karni/ui` and the
`karni` command. If something would be written in more than one project, it
belongs there — and when it is missing, Karni's own reference app records it
in [FRICTION.md](https://github.com/cbsshekhawat18-lab/karni/blob/main/examples/eventhub/FRICTION.md)
and the next release fixes it.

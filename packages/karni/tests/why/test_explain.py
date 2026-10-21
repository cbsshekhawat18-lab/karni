"""``Predicate.explain()`` shares the predicates' own logic; the trace records real decisions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.db.models import Q

from karni.api.access import (
    TRACE_ATTR,
    AccessEvent,
    Authenticated,
    Can,
    HasRole,
    Owned,
    Public,
    Where,
    trace,
)
from karni.vetoes import VetoContext, check_vetoes, first_veto, register_veto, unregister_veto
from tests.testapp.models import Event

pytestmark = pytest.mark.django_db


def _request(user: Any) -> Any:
    return SimpleNamespace(user=user, method="GET")


PREDICATES = (
    Public(),
    Authenticated(),
    HasRole("staff"),
    Owned("organizer"),
    Owned("organizer", bypass=HasRole("staff")),
    Can("testapp.event:view"),
    Can("testapp.event:view", "testapp.event:approve"),
    Where(lambda request: Q(status="published")),
    Where(lambda request: False),
    Owned("organizer") | HasRole("staff") | Where(lambda request: Q(status="published")),
    (Owned("organizer") | HasRole("reader")) & Authenticated(),
    Can("testapp.event:change") & (Owned("organizer") | HasRole("staff")),
)


def test_explain_answers_exactly_what_allows_and_rows_answer(world: Any) -> None:
    checked = 0
    for user in world.users.values():
        request = _request(user)
        for predicate in PREDICATES:
            explained = predicate.explain(request)
            assert explained.allows == predicate.allows(request), (predicate, user)
            assert explained.rows == predicate.rows(request), (predicate, user)
            leaves = list(explained.leaves())
            assert leaves and all(not leaf.parts for leaf in leaves)
            checked += 1
    assert checked == len(PREDICATES) * len(world.users)


def test_leaf_facts_say_what_the_evaluation_read(world: Any) -> None:
    alice = world.users["alice"]
    request = _request(alice)
    facts = HasRole("staff").explain(request).facts
    assert facts == {"required": ["staff"], "held": ["organizer"]}
    grants = Can("testapp.event:view").explain(request).facts["permissions"]["testapp.event:view"]
    assert [(g.scope, rows) for g, rows in grants["grants"]] == [("own", Q(organizer=alice))]
    assert [(s.role, s.origin) for s in grants["sources"]] == [("organizer", "declared")]
    owned = Owned("organizer", bypass=HasRole("staff")).explain(request)
    assert [type(part.predicate).__name__ for part in owned.parts] == ["Owned", "HasRole"]


def test_trace_is_a_no_op_unless_a_list_listens() -> None:
    quiet = SimpleNamespace()
    trace(quiet, "gate", allowed=True)
    assert not hasattr(quiet, TRACE_ATTR)
    events: list[AccessEvent] = []
    loud = SimpleNamespace(**{TRACE_ATTR: events})
    trace(loud, "gate", allowed=False)
    assert events == [AccessEvent("gate", {"allowed": False})]


def test_first_veto_names_the_veto_check_vetoes_answers_with() -> None:
    register_veto(lambda context: "no" if context.action == "destroy" else None, name="t.v")
    try:
        context = VetoContext(None, "api", "destroy", model=Event)
        assert first_veto(context) == ("t.v", "no")
        assert check_vetoes(context) == "no"
        assert first_veto(VetoContext(None, "api", "list", model=Event)) is None
    finally:
        unregister_veto("t.v")

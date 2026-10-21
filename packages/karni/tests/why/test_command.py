"""``manage.py karni_why``: every target form, text and JSON, and the coded refusals."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from karni.exceptions import KarniCommandError

pytestmark = pytest.mark.django_db


def _run(*args: str) -> str:
    out = StringIO()
    call_command("karni_why", *args, stdout=out)
    return out.getvalue()


def test_a_row_filtered_out_by_the_read_scope(world: Any) -> None:
    row = world.rows["bob-draft"]
    text = _run(f"declared-events/{row.pk}", "--as", "alice@example.com")
    lines = text.splitlines()
    assert lines[0].startswith("user     alice@example.com")
    assert lines[1] == "roles    organizer"
    assert "row      Event" in text and "organizer=bob@example.com" in text
    assert "result   404 Not Found — the row exists but access.read filters it out" in text
    assert "tests/why/routes.py" in text and "karni/api/viewsets.py" in text
    assert "fix      " in text


def test_a_grant_scope_names_the_role_and_the_rows(world: Any) -> None:
    row = world.rows["bob-draft"]
    text = _run(f"granted-events/{row.pk}", "--as", "alice@example.com")
    assert "grants   testapp.event:view  scope own  (role 'organizer', KARNI_ROLES" in text
    assert "→ organizer = you" in text
    assert "scope 'all'" in text  # the second alternative


def test_a_write_refused_on_a_readable_row(world: Any) -> None:
    row = world.rows["bob-published"]
    text = _run(f"declared-events/{row.pk}", "--as", "alice@example.com", "--action", "update")
    assert "result   403 Forbidden — the row is readable" in text
    assert "make alice@example.com the row's organizer (now bob@example.com)" in text


def test_json_for_agents(world: Any) -> None:
    row = world.rows["bob-draft"]
    data = json.loads(_run(f"granted-events/{row.pk}", "--as", "alice@example.com", "--json"))
    assert data["outcome"] == "filtered" and data["status"] == 404
    assert data["roles"] == ["organizer"]
    assert data["grants"][0]["grants"][0]["scope"] == "own"
    assert data["read"]["leaves"][0]["matches_row"] is False
    assert data["row"]["values"] == {"organizer": "bob@example.com"}
    assert 1 <= len(data["fix"]) <= 2


def test_a_hidden_field_and_a_read_only_field(world: Any) -> None:
    hidden = _run("customers.salary", "--as", "alice@example.com")
    assert "result   hidden — salary is absent" in hidden
    assert "Customer.Karni.field_roles['salary']: read needs one of staff" in hidden
    owner = _run("declared-events.organizer", "--as", "alice@example.com")
    assert "result   read-only" in owner and "owner field" in owner
    status = _run("testapp.Event.status", "--as", "staff@example.com")
    assert "APIMeta.read_only lists it" in status


def test_why_empty_counts_each_step(world: Any) -> None:
    text = _run("declared-events", "--empty", "--as", "bob@example.com", "--param", "status=draft")
    assert "steps" in text and "model scope soft_delete" in text
    assert "KarniFilterBackend" in text
    data = json.loads(_run("granted-events", "--empty", "--as", "reader@example.com", "--json"))
    assert data["outcome"] == "not-empty" and data["count"] == 5
    removed = {step["step"]: step["removed"] for step in data["steps"]}
    assert removed["model scope soft_delete"] == 1


def test_a_list_empty_because_of_the_roles_grant(world: Any) -> None:
    # Loaded from the database, the manager has no `venue`: related:venue reaches nothing.
    data = json.loads(_run("granted-events", "--empty", "--as", "manager@example.com", "--json"))
    assert data["outcome"] == "empty" and data["count"] == 0
    assert data["grants"][0]["grants"][0]["scope"] == "related:venue"
    assert "access.read removes all 5 row(s)" in data["summary"]


@pytest.mark.parametrize(
    ("args", "code", "phrase"),
    [
        (("nothing/1", "--as", "alice@example.com"), "E901", "Routed resources"),
        (("customers/1", "--as", "who@example.com"), "E902", "No user matches"),
        (("customers.nope", "--as", "alice@example.com"), "E905", "API fields"),
        (("customers/1", "--as", "alice@example.com", "--action", "fly"), "E906", "Actions"),
        (("customers/1",), "E908", "needs --as"),
        (("403",), "E908", "needs the request id"),
        (("403", "missing-id"), "E903", "No request record"),
    ],
)
def test_coded_refusals(world: Any, args: tuple[str, ...], code: str, phrase: str) -> None:
    with pytest.raises(KarniCommandError) as caught:
        _run(*args)
    assert caught.value.code == code
    assert phrase in str(caught.value)

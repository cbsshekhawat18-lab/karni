"""``karni why`` and ``karni why-empty`` name the tree grant and the node that decided."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import call_command

from karni.accounts import grants
from tests.treescope import PRODUCT_VIEW
from tests.treescope.conftest import Catalog, make_user

pytestmark = pytest.mark.django_db


def run(*args: str) -> str:
    out = StringIO()
    call_command("karni_why", *args, stdout=out)
    return out.getvalue()


def test_the_grant_and_the_node_that_let_a_row_in(catalog: Catalog) -> None:
    user = make_user("reader@example.com")
    row = grants.grant(None, user, PRODUCT_VIEW, "tree:regions", targets=[catalog.europe.pk])
    text = run(f"products/{catalog.milk.pk}", "--as", "reader@example.com")
    assert "result   200 OK" in text
    assert "→ regions under 'Europe'  ← reaches this row" in text
    assert f"user grant {row.pk} targets Europe, and this row's regions France is under it" in text


def test_the_grant_and_the_node_that_kept_a_row_out(catalog: Catalog) -> None:
    user = make_user("outside@example.com")
    row = grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[catalog.food.pk])
    text = run(f"products/{catalog.saw.pk}", "--as", "outside@example.com")
    assert "404 Not Found" in text
    assert f"user grant {row.pk} targets Food, and this row's category Saws is under none" in text
    assert f"or a node above it to the targets of user grant {row.pk}" in text
    data = json.loads(run(f"products/{catalog.saw.pk}", "--as", "outside@example.com", "--json"))
    entry = data["grants"][0]["grants"][0]
    assert entry["reaches_row"] is False
    assert entry["tree"]["nodes"] == [{"id": str(catalog.food.pk), "label": "Food"}]
    assert entry["tree"]["values"] == [{"id": str(catalog.saws.pk), "label": "Saws"}]
    assert entry["tree"]["under"] is None


def test_a_granted_node_that_is_the_row_s_own(catalog: Catalog) -> None:
    make_user("exact@example.com")
    user = make_user("exact2@example.com")
    grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[catalog.dairy.pk])
    text = run(f"products/{catalog.milk.pk}", "--as", "exact2@example.com")
    assert "and this row's category is Dairy" in text


def test_a_role_grant_without_a_node(catalog: Catalog) -> None:
    make_user("buyer@example.com", "buyer")
    text = run(f"products/{catalog.milk.pk}", "--as", "buyer@example.com")
    assert (
        "role 'buyer' (through buyer@example.com.category, which User does not have) gives no node"
    ) in text
    assert "set buyer@example.com.category" not in text


def test_a_role_grant_through_an_attribute_the_user_model_has(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.contrib.auth import get_user_model

    monkeypatch.setattr(get_user_model(), "category", None, raising=False)
    make_user("holder@example.com", "buyer")
    text = run(f"products/{catalog.milk.pk}", "--as", "holder@example.com")
    assert "role 'buyer' (through holder@example.com.category) gives no node" in text
    assert fixes(text)[0].startswith("set holder@example.com.category to the row's category (Dairy")


def test_why_empty_names_the_nodes(catalog: Catalog) -> None:
    user = make_user("empty@example.com")
    row = grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[catalog.books.pk])
    data = json.loads(run("products", "--empty", "--as", "empty@example.com", "--json"))
    assert data["count"] == 1
    entry = data["grants"][0]["grants"][0]
    assert entry["tree"]["nodes"] == [{"id": str(catalog.books.pk), "label": "Books"}]
    text = run("products", "--empty", "--as", "empty@example.com")
    assert f"user grant {row.pk} targets Books" in text
    assert "category under 'Books'" in text
    bare = make_user("bare@example.com")
    grants.grant(None, bare, PRODUCT_VIEW, "tree:category")
    text = run("products", "--empty", "--as", "bare@example.com")
    assert "gives no node, so it reaches no row" in text


def fixes(text: str) -> list[str]:
    """The ``fix`` section's lines, without the label and the ``or:``."""
    lines = text.split("\nfix      ", 1)[1].splitlines() if "\nfix      " in text else []
    found: list[str] = []
    for line in lines:
        if found and not line.startswith(" "):
            break
        found.append(line.strip().removeprefix("or: "))
    return found


def test_a_row_outside_every_grant_names_the_user_grant_to_widen(catalog: Catalog) -> None:
    # The role reads user.category, which the user model does not have (W620),
    # and two user grants give the nodes: the fix widens a grant.
    user = make_user("two-grants@example.com", "buyer")
    food = grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[catalog.food.pk])
    books = grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[catalog.books.pk])
    text = run(f"products/{catalog.saw.pk}", "--as", "two-grants@example.com")
    assert "404 Not Found" in text
    first = fixes(text)[0]
    assert f"or a node above it to the targets of user grant {food.pk} (or of {books.pk})" in first
    assert f"targets=[*grant.targets, '{catalog.saws.pk}']" in first
    assert ".category to the row's" not in text  # no attribute the user model lacks
    assert "(through two-grants@example.com.category, which User does not have)" in text


def test_a_role_without_a_node_and_no_user_grant_names_the_grant_to_add(
    catalog: Catalog,
) -> None:
    make_user("role-only@example.com", "buyer")
    text = run(f"products/{catalog.milk.pk}", "--as", "role-only@example.com")
    first = fixes(text)[0]
    assert first.startswith(
        "give role-only@example.com a user grant of 'testapp.product:view' at scope "
        "'tree:category' on the row's category"
    )
    assert (
        f"grants.grant(operator, user, 'testapp.product:view', 'tree:category', "
        f"targets=['{catalog.dairy.pk}'])" in first
    )
    assert "grant role 'buyer' 'testapp.product:view' at scope 'all'" in fixes(text)[1]

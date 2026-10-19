"""Field-level visibility (ADR 0002, P3): ``Karni.field_roles`` on every surface of the API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from drf_spectacular.generators import SchemaGenerator
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.accounts.permissions import assign_role
from karni.accounts.visibility import hidden_fields, protected_fields
from karni.api import Access, Authenticated, BaseViewSet
from karni.api.filters import KarniFilterBackend
from karni.api.routers import KarniRouter
from karni.checks import check_field_roles, check_viewsets
from tests.testapp.models import Customer, Event, Ticket

pytestmark = pytest.mark.django_db

ROUTER = "tests.api.test_field_roles"


class CustomerViewSet(BaseViewSet):
    model = Customer
    access = Access(read=Authenticated(), write=Authenticated())
    search_fields = ["name", "internal_note"]


class TicketViewSet(BaseViewSet):
    model = Ticket
    access = Access(read=Authenticated(), write=Authenticated())


class NoteSearchEvents(BaseViewSet):
    """``internal_note`` is write-only on Event: searching it is E131."""

    model = Event
    access = Access(read=Authenticated(), write=Authenticated())
    search_fields = ["title", "internal_note"]


def router() -> KarniRouter:
    found = KarniRouter()
    found.register("customers", CustomerViewSet, basename="customers")
    found.register("tickets", TicketViewSet, basename="tickets")
    found.autodiscover()
    return found


def note_router() -> KarniRouter:
    found = KarniRouter()
    found.register("note-events", NoteSearchEvents, basename="note-events")
    return found


def _user(email: str, *roles: str, **flags: Any) -> Any:
    user = get_user_model().objects.create_user(
        email=email, password="a-strong-password-123", **flags
    )
    for role in roles:
        assign_role(user, role)
    return user


def _customer(name: str, **fields: Any) -> Customer:
    fields.setdefault("phone", "+1 555 0100")
    fields.setdefault("internal_note", "")
    fields.setdefault("salary", Decimal("1000.00"))
    return Customer.objects.create(name=name, **fields)


def _call(
    viewset: type[Any],
    actions: dict[str, str],
    *,
    user: Any = None,
    method: str = "get",
    data: Any = None,
    query: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    factory = APIRequestFactory()
    if method == "get":
        request = factory.get("/", query or {})
    else:
        request = getattr(factory, method)("/", data or {}, format="json")
    if user is not None:
        force_authenticate(request, user=user)
    return viewset.as_view(actions)(request, **kwargs)


def _list(viewset: type[Any], user: Any, **query: Any) -> list[dict[str, Any]]:
    response = _call(viewset, {"get": "list"}, user=user, query=query)
    assert response.status_code == 200, response.data
    return list(response.data["results"])


@pytest.fixture
def staff() -> Any:
    return _user("staff@example.com", "staff")


@pytest.fixture
def member() -> Any:
    return _user("member@example.com", "user")


# the helper


def test_hidden_and_protected_follow_the_roles(staff: Any, member: Any) -> None:
    nobody = _user("nobody@example.com")
    root = _user("root@example.com", is_superuser=True)
    assert hidden_fields(Customer, staff) == frozenset()
    assert hidden_fields(Customer, member) == {"internal_note", "salary"}
    assert hidden_fields(Customer, nobody) == {"phone", "internal_note", "salary"}
    assert hidden_fields(Customer, None) == {"phone", "internal_note", "salary"}
    assert hidden_fields(Customer, root) == frozenset()
    assert protected_fields(Customer, member) == {"phone", "internal_note", "salary"}
    assert protected_fields(Customer, staff) == frozenset()
    assert hidden_fields(Event, member) == frozenset()  # no field_roles: nothing hidden


# the API


def test_hidden_fields_are_absent_not_null(staff: Any, member: Any) -> None:
    row = _customer("Ada", internal_note="vip", salary=Decimal("9000.00"))
    as_member = _call(CustomerViewSet, {"get": "retrieve"}, user=member, pk=str(row.pk)).data
    assert as_member["phone"] == "+1 555 0100"
    assert "internal_note" not in as_member and "salary" not in as_member
    as_staff = _call(CustomerViewSet, {"get": "retrieve"}, user=staff, pk=str(row.pk)).data
    assert as_staff["internal_note"] == "vip" and as_staff["salary"] == "9000.00"
    listed = _list(CustomerViewSet, member)
    assert listed and "salary" not in listed[0] and "phone" in listed[0]
    nobody = _user("nobody@example.com")
    assert "phone" not in _list(CustomerViewSet, nobody)[0]


def test_write_protected_fields_are_rejected_naming_the_roles(staff: Any, member: Any) -> None:
    row = _customer("Ada")
    refused = _call(
        CustomerViewSet,
        {"patch": "partial_update"},
        user=member,
        method="patch",
        data={"phone": "+1 555 0199", "name": "Ada L."},
        pk=str(row.pk),
    )
    assert refused.status_code == 400
    assert refused.data == {"phone": ["Only roles staff may change phone."]}
    row.refresh_from_db()
    assert row.phone == "+1 555 0100" and row.name == "Ada"
    allowed = _call(
        CustomerViewSet,
        {"patch": "partial_update"},
        user=member,
        method="patch",
        data={"name": "Ada L."},
        pk=str(row.pk),
    )
    assert allowed.status_code == 200, allowed.data
    silent = _call(  # a field the member cannot even see is simply unknown input
        CustomerViewSet,
        {"patch": "partial_update"},
        user=member,
        method="patch",
        data={"internal_note": "planted", "salary": "1"},
        pk=str(row.pk),
    )
    assert silent.status_code == 200
    row.refresh_from_db()
    assert row.internal_note == "" and row.salary == Decimal("1000.00")
    by_staff = _call(
        CustomerViewSet,
        {"patch": "partial_update"},
        user=staff,
        method="patch",
        data={"phone": "+1 555 0199", "salary": "2.50"},
        pk=str(row.pk),
    )
    assert by_staff.status_code == 200, by_staff.data
    row.refresh_from_db()
    assert row.phone == "+1 555 0199" and row.salary == Decimal("2.50")


def test_create_cannot_set_a_protected_field(member: Any) -> None:
    response = _call(
        CustomerViewSet,
        {"post": "create"},
        user=member,
        method="post",
        data={"name": "New", "phone": "+1 555 0100"},
    )
    assert response.status_code == 400 and "phone" in response.data
    assert Customer.objects.count() == 0


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.router")
def test_nested_expansion_hides_the_same_fields(staff: Any, member: Any) -> None:
    customer = _customer("Ada", internal_note="vip", salary=Decimal("9000.00"))
    Ticket.objects.create(customer=customer, subject="Help")
    as_member = _list(TicketViewSet, member, expand="customer")[0]["customer"]
    assert as_member["name"] == "Ada" and as_member["phone"] == "+1 555 0100"
    assert "salary" not in as_member and "internal_note" not in as_member
    as_staff = _list(TicketViewSet, staff, expand="customer")[0]["customer"]
    assert as_staff["salary"] == "9000.00"


def _schema_as(user: Any) -> dict[str, Any]:
    """The document ``/api/schema/`` serves ``user`` (``public=False``: their endpoints only)."""
    request = Request(APIRequestFactory().get("/api/schema/"))
    request.user = user
    request.auth = None  # resolved, as after real authentication; the generator reads it
    return SchemaGenerator(patterns=router().urls).get_schema(request=request, public=False)


def test_the_schema_is_generated_per_role(staff: Any, member: Any) -> None:
    member_schema = _schema_as(member)
    for_member = member_schema["components"]["schemas"]
    for_staff = _schema_as(staff)["components"]["schemas"]
    assert "TestappCustomerRequest" in for_member, (
        sorted(for_member),
        {path: sorted(ops) for path, ops in member_schema["paths"].items()},
    )
    member_fields = for_member["TestappCustomer"]["properties"]
    staff_fields = for_staff["TestappCustomer"]["properties"]
    assert "salary" not in member_fields and "internal_note" not in member_fields
    assert member_fields["phone"].get("readOnly") is True  # readable, not writable
    assert "salary" in staff_fields and "internal_note" in staff_fields
    assert not staff_fields["phone"].get("readOnly")
    assert "phone" not in for_member["TestappCustomerRequest"]["properties"]
    assert "phone" in for_staff["TestappCustomerRequest"]["properties"]


def test_ordering_by_a_hidden_field_is_ignored(staff: Any, member: Any) -> None:
    rich = _customer("Rich", salary=Decimal("9000.00"))
    poor = _customer("Poor", salary=Decimal("1.00"))  # newer: first by default
    default = [str(poor.pk), str(rich.pk)]
    assert [row["id"] for row in _list(CustomerViewSet, member)] == default
    assert [row["id"] for row in _list(CustomerViewSet, member, ordering="salary")] == default
    assert [row["id"] for row in _list(CustomerViewSet, staff, ordering="salary")] == [
        str(poor.pk),
        str(rich.pk),
    ]
    assert [row["id"] for row in _list(CustomerViewSet, staff, ordering="-salary")] == [
        str(rich.pk),
        str(poor.pk),
    ]
    assert [row["id"] for row in _list(CustomerViewSet, member, ordering="name")] == [
        str(poor.pk),
        str(rich.pk),
    ]


def test_filtering_on_a_hidden_field_is_ignored_and_undocumented(staff: Any, member: Any) -> None:
    _customer("Rich", salary=Decimal("9000.00"))
    _customer("Poor", salary=Decimal("1.00"))
    assert len(_list(CustomerViewSet, member, salary__gte="100")) == 2
    assert len(_list(CustomerViewSet, staff, salary__gte="100")) == 1
    assert len(_list(CustomerViewSet, member, name="Rich")) == 1

    def parameters(user: Any) -> set[str]:  # what the schema documents for this role
        operation = _schema_as(user)["paths"]["/customers/"]["get"]
        return {parameter["name"] for parameter in operation["parameters"]}

    assert "salary__gte" in parameters(staff)
    assert not {"salary", "salary__gte", "internal_note"} & parameters(member)
    view = CustomerViewSet()
    view.action, view.format_kwarg, view.args, view.kwargs = "list", None, (), {}
    request = Request(APIRequestFactory().get("/"))
    request.user = member
    view.request = request
    narrowed = KarniFilterBackend().get_filterset_class(view, Customer.objects.all())
    assert narrowed is not None and "salary__gte" not in narrowed.base_filters


def test_search_over_a_hidden_field_is_ignored(staff: Any, member: Any) -> None:
    _customer("Ada", internal_note="needle in the note")
    _customer("Bob")
    assert [row["name"] for row in _list(CustomerViewSet, staff, search="needle")] == ["Ada"]
    assert _list(CustomerViewSet, member, search="needle") == []  # the note does not exist
    assert [row["name"] for row in _list(CustomerViewSet, member, search="Ada")] == ["Ada"]


# the checks


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.note_router")
def test_search_over_a_write_only_field_fails_the_boot() -> None:
    messages = [m for m in check_viewsets() if m.id == "karni.E131"]
    assert len(messages) == 1
    assert "NoteSearchEvents.search_fields names internal_note" in messages[0].msg


def test_field_roles_check(monkeypatch: pytest.MonkeyPatch) -> None:
    assert check_field_roles() == []
    with override_settings(KARNI_ROLES={"staff": {"grants": {"*": "all"}}}):
        messages = check_field_roles()
    assert [m.id for m in messages] == ["karni.E212"]
    assert "'phone'" in messages[0].msg and "user" in messages[0].msg
    monkeypatch.setattr(Customer.Karni, "field_roles", {"nope": ["staff"]})
    messages = check_field_roles()
    assert len(messages) == 1 and "'nope'" in messages[0].msg
    monkeypatch.setattr(Customer.Karni, "field_roles", {"phone": "staff"})
    messages = check_field_roles()
    assert [m.id for m in messages] == ["karni.E212"] and "must list role slugs" in messages[0].msg

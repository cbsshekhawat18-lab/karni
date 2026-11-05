from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import BASE, Api, money, rows, unique


def make_resource(staff: Api, price: str = "30.00") -> dict[str, Any]:
    reply = staff.post("resources/", {"name": unique("room"), "description": "d", "price": price})
    assert reply.status_code == 201, reply.text
    return reply.json()


def make_slot(staff: Api, resource: dict[str, Any], capacity: int = 2) -> dict[str, Any]:
    start = datetime.now(UTC) + timedelta(days=3)
    reply = staff.post(
        "slots/",
        {
            "resource": resource["id"],
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
            "capacity": capacity,
        },
    )
    assert reply.status_code == 201, reply.text
    return reply.json()


def book(member: Api, slot: dict[str, Any]) -> dict[str, Any]:
    reply = member.post("bookings/", {"slot": slot["id"], "note": "hello"})
    assert reply.status_code == 201, reply.text
    return reply.json()


def remaining(api: Api, slot: dict[str, Any]) -> int:
    return api.get(f"slots/{slot['id']}/").json()["remaining"]


def payment_of(reply_json: dict[str, Any]) -> dict[str, Any]:
    return reply_json["payment"] if isinstance(reply_json.get("payment"), dict) else reply_json


def test_sign_in_and_protection(anonymous):
    assert anonymous.get(f"{BASE}/api/resources/").status_code in (401, 403)
    assert anonymous.get(f"{BASE}/api/bookings/").status_code in (401, 403)
    bad = anonymous.post(
        f"{BASE}/api/auth/login/", json={"email": "staff@bench.test", "password": "wrong"}
    )
    assert bad.status_code in (400, 401)


def test_staff_publish_resources_and_members_cannot(api):
    staff, member = api("staff"), api("member")
    resource = make_resource(staff)
    assert money(resource["price"]) == money("30.00")
    assert member.post("resources/", {"name": "x", "price": "1.00"}).status_code == 403
    assert staff.post("resources/", {"price": "1.00"}).status_code == 400
    assert staff.post("resources/", {"name": unique("r"), "price": "-1"}).status_code == 400
    assert resource["id"] in [r["id"] for r in rows(member.get("resources/"))]
    assert member.get(f"resources/{resource['id']}/").status_code == 200
    assert staff.patch(f"resources/{resource['id']}/", {"description": "new"}).status_code == 200


def test_slots_are_staff_only_and_validated(api):
    staff, member = api("staff"), api("member")
    resource = make_resource(staff)
    slot = make_slot(staff, resource, capacity=3)
    assert slot["capacity"] == 3 and slot["remaining"] == 3
    assert slot["resource"] == resource["id"]
    start = datetime.now(UTC) + timedelta(days=4)
    body = {"resource": resource["id"], "starts_at": start.isoformat(), "capacity": 2}
    assert member.post("slots/", {**body, "ends_at": (start + timedelta(hours=1)).isoformat()}).status_code == 403
    assert staff.post("slots/", {**body, "ends_at": (start - timedelta(hours=1)).isoformat()}).status_code == 400
    assert staff.post("slots/", {**body, "ends_at": start.isoformat()}).status_code == 400
    late = (start + timedelta(hours=1)).isoformat()
    assert staff.post("slots/", {**body, "capacity": 0, "ends_at": late}).status_code == 400
    found = rows(member.get("slots/", params={"resource": resource["id"]}))
    assert [s["id"] for s in found] == [slot["id"]]


def test_a_booking_takes_a_place(api):
    staff, member = api("staff"), api("member")
    slot = make_slot(staff, make_resource(staff), capacity=2)
    booking = book(member, slot)
    assert booking["status"] == "pending"
    assert booking["slot"] == slot["id"]
    assert booking["payment"] is None
    assert remaining(member, slot) == 1


def test_a_full_slot_refuses_with_409_and_changes_nothing(api):
    staff, one, two = api("staff"), api("member"), api("member2")
    slot = make_slot(staff, make_resource(staff), capacity=1)
    book(one, slot)
    refused = two.post("bookings/", {"slot": slot["id"]})
    assert refused.status_code == 409
    assert remaining(two, slot) == 0
    assert len([b for b in rows(two.get("bookings/")) if b["slot"] == slot["id"]]) == 0


def test_staff_cannot_book_and_unknown_slots_are_refused(api):
    staff, member = api("staff"), api("member")
    slot = make_slot(staff, make_resource(staff))
    assert staff.post("bookings/", {"slot": slot["id"]}).status_code == 403
    assert member.post("bookings/", {"slot": 987654321}).status_code == 400
    assert member.post("bookings/", {}).status_code == 400


def test_members_see_only_their_bookings_and_staff_see_all(api):
    staff, one, two = api("staff"), api("member"), api("member2")
    slot = make_slot(staff, make_resource(staff), capacity=5)
    booking = book(one, slot)
    assert booking["id"] in [b["id"] for b in rows(one.get("bookings/"))]
    assert booking["id"] not in [b["id"] for b in rows(two.get("bookings/"))]
    assert two.get(f"bookings/{booking['id']}/").status_code in (403, 404)
    assert one.get(f"bookings/{booking['id']}/").status_code == 200
    assert booking["id"] in [b["id"] for b in rows(staff.get("bookings/"))]
    assert staff.get(f"bookings/{booking['id']}/").status_code == 200


def test_cancelling_gives_the_place_back_once(api):
    staff, one, two = api("staff"), api("member"), api("member2")
    slot = make_slot(staff, make_resource(staff), capacity=1)
    booking = book(one, slot)
    assert two.post(f"bookings/{booking['id']}/cancel/").status_code in (403, 404)
    cancelled = one.post(f"bookings/{booking['id']}/cancel/")
    assert cancelled.status_code == 200, cancelled.text
    assert one.get(f"bookings/{booking['id']}/").json()["status"] == "cancelled"
    assert remaining(one, slot) == 1
    assert one.post(f"bookings/{booking['id']}/cancel/").status_code in (400, 409)
    assert remaining(one, slot) == 1
    assert book(two, slot)["status"] == "pending"


def test_staff_can_cancel_any_booking(api):
    staff, member = api("staff"), api("member")
    slot = make_slot(staff, make_resource(staff))
    booking = book(member, slot)
    assert staff.post(f"bookings/{booking['id']}/cancel/").status_code == 200
    assert remaining(staff, slot) == 2


def test_paying_opens_a_payment_for_the_resource_price(api):
    staff, member = api("staff"), api("member")
    slot = make_slot(staff, make_resource(staff, price="45.50"))
    booking = book(member, slot)
    reply = member.post(f"bookings/{booking['id']}/pay/")
    assert reply.status_code in (200, 201), reply.text
    payment = payment_of(reply.json())
    assert payment["status"] == "pending"
    assert money(payment["amount"]) == money("45.50")
    assert payment["currency"]
    shown = member.get(f"bookings/{booking['id']}/").json()
    assert shown["payment"] == payment["id"] or shown["payment"]["id"] == payment["id"]
    assert member.get(f"payments/{payment['id']}/").status_code == 200
    assert member.post(f"bookings/{booking['id']}/pay/").status_code in (400, 409)


def test_confirming_the_payment_confirms_the_booking(api):
    staff, member = api("staff"), api("member")
    booking = book(member, make_slot(staff, make_resource(staff)))
    payment = payment_of(member.post(f"bookings/{booking['id']}/pay/").json())
    confirmed = member.post(f"payments/{payment['id']}/confirm/")
    assert confirmed.status_code == 200, confirmed.text
    assert member.get(f"bookings/{booking['id']}/").json()["status"] == "confirmed"
    assert member.get(f"payments/{payment['id']}/").json()["status"] == "succeeded"
    assert member.post(f"payments/{payment['id']}/confirm/").status_code == 200
    assert member.get(f"bookings/{booking['id']}/").json()["status"] == "confirmed"


def test_only_the_owner_or_staff_confirm_and_pay(api):
    staff, one, two = api("staff"), api("member"), api("member2")
    booking = book(one, make_slot(staff, make_resource(staff), capacity=3))
    assert two.post(f"bookings/{booking['id']}/pay/").status_code in (403, 404)
    payment = payment_of(one.post(f"bookings/{booking['id']}/pay/").json())
    assert two.post(f"payments/{payment['id']}/confirm/").status_code in (403, 404)
    assert two.get(f"payments/{payment['id']}/").status_code in (403, 404)
    assert staff.get(f"payments/{payment['id']}/").status_code == 200
    assert staff.post(f"payments/{payment['id']}/confirm/").status_code == 200


def test_a_cancelled_booking_cannot_be_paid(api):
    staff, member = api("staff"), api("member")
    booking = book(member, make_slot(staff, make_resource(staff)))
    member.post(f"bookings/{booking['id']}/cancel/")
    assert member.post(f"bookings/{booking['id']}/pay/").status_code in (400, 409)

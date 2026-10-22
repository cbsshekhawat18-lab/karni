"""no_overlap on PostgreSQL: the EXCLUDE constraint refuses a double booking, even from raw SQL.

Every test here needs PostgreSQL (and psycopg for the range columns): SQLite
has no EXCLUDE, so the constraint creates nothing there and system check
karni.W980 says so (``test_checks.py`` covers that side).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction

from karni.constraints import OverlapConflict
from tests.lifecycleapp.models import HAS_RANGES, Room, Slot

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="EXCLUDE constraints exist only on PostgreSQL (CI's Postgres step runs these)",
    ),
    pytest.mark.skipif(not HAS_RANGES, reason="range columns need psycopg"),
]

T0 = dt.datetime(2026, 10, 21, 10, 0, tzinfo=dt.UTC)


def at(hours: float) -> dt.datetime:
    return T0 + dt.timedelta(hours=hours)


def span(start: float, end: float) -> object:
    from psycopg.types.range import Range

    return Range(at(start), at(end), "[)")


def _reservation_model() -> Any:
    from tests.lifecycleapp.models import Reservation

    return Reservation


def _raw_insert(room: Room, start: float, end: float, status: str = "held") -> None:
    table = connection.ops.quote_name(_reservation_model()._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (id, created_at, updated_at, room_id, during, status) "
            "VALUES (%s, now(), now(), %s, tstzrange(%s, %s, '[)'), %s)",
            [uuid.uuid4(), room.pk, at(start), at(end), status],
        )


@pytest.fixture
def room() -> Room:
    return Room.objects.create(name="Blue")


def test_the_constraint_is_an_exclude_using_gist_with_the_live_rows_condition() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            ["lifecycleapp_reservation_room_during_no_overlap"],
        )
        (definition,) = cursor.fetchone()
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        assert cursor.fetchone() == (1,)
    assert definition.startswith("EXCLUDE USING gist (room_id WITH =, during WITH &&) WHERE ")
    assert "deleted_at IS NULL" in definition and "'cancelled'" in definition


def test_a_raw_insert_of_an_overlapping_booking_is_rejected(room: Room) -> None:
    _raw_insert(room, 0, 2)
    with pytest.raises(IntegrityError, match="lifecycleapp_reservation_room_during_no_overlap"):
        with transaction.atomic():
            _raw_insert(room, 1, 3)
    assert _reservation_model().objects.count() == 1


def test_another_room_and_touching_ranges_are_fine(room: Room) -> None:
    other = Room.objects.create(name="Red")
    _raw_insert(room, 0, 2)
    _raw_insert(other, 0, 2)  # another resource
    _raw_insert(room, 2, 3)  # [10:00, 12:00) and [12:00, 13:00) touch, they do not overlap
    _raw_insert(room, -1, 0)
    assert _reservation_model().objects.count() == 4


def test_a_cancelled_booking_does_not_block_the_slot(room: Room) -> None:
    Reservation = _reservation_model()
    first = Reservation.objects.create(room=room, during=span(0, 2))
    first.transition("status", "cancelled")
    _raw_insert(room, 0, 2)  # the database accepts it: cancelled rows are outside the WHERE
    assert Reservation.objects.filter(status="held").count() == 1


def test_a_soft_deleted_booking_does_not_block_the_slot(room: Room) -> None:
    Reservation = _reservation_model()
    Reservation.objects.create(room=room, during=span(0, 2)).delete()
    Reservation.objects.create(room=room, during=span(0, 2))
    assert Reservation.objects.count() == 1


def test_restoring_or_reviving_into_a_taken_slot_is_refused(room: Room) -> None:
    Reservation = _reservation_model()
    gone = Reservation.objects.create(room=room, during=span(0, 2))
    gone.delete()
    Reservation.objects.create(room=room, during=span(1, 3))
    with pytest.raises(OverlapConflict):
        gone.restore()


def test_the_orm_names_the_booking_in_the_way(room: Room) -> None:
    Reservation = _reservation_model()
    existing = Reservation.objects.create(room=room, during=span(0, 2))
    with pytest.raises(OverlapConflict) as raised:
        Reservation.objects.create(room=room, during=span(1, 3))
    error = raised.value
    assert error.code == "E984" and error.status == 409 and error.field == "during"
    assert error.details["existing"] == str(existing.pk)
    assert error.details["constraint"] == "lifecycleapp_reservation_room_during_no_overlap"
    assert f"it overlaps Reservation {existing.pk} (room {room.pk}, during" in error.message
    assert "status 'held'" in error.message
    assert Reservation.objects.count() == 1  # and the surrounding transaction is still usable


def test_moving_a_booking_onto_another_is_refused(room: Room) -> None:
    Reservation = _reservation_model()
    Reservation.objects.create(room=room, during=span(0, 2))
    later = Reservation.objects.create(room=room, during=span(3, 4))
    later.during = span(1, 4)
    with pytest.raises(OverlapConflict):
        later.save()


def test_a_pair_of_plain_columns_is_enforced_the_same_way(room: Room) -> None:
    Slot.objects.create(room=room, starts_at=at(0), ends_at=at(2))
    Slot.objects.create(room=room, starts_at=at(2), ends_at=at(3))  # touching
    with pytest.raises(OverlapConflict) as raised:
        Slot.objects.create(room=room, starts_at=at(1), ends_at=at(2.5))
    assert raised.value.field == "starts_at"
    table = connection.ops.quote_name(Slot._meta.db_table)
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (id, created_at, updated_at, room_id, starts_at, ends_at, status)"
            " VALUES (%s, now(), now(), %s, %s, %s, 'held')",
            [uuid.uuid4(), room.pk, at(0.5), at(1)],
        )


def test_the_tuple_shorthand_blocks_every_live_row(room: Room) -> None:
    from psycopg.types.range import Range

    from tests.lifecycleapp.models import Stay

    Stay.objects.create(room=room, nights=Range(dt.date(2026, 10, 1), dt.date(2026, 10, 4)))
    Stay.objects.create(room=room, nights=Range(dt.date(2026, 10, 4), dt.date(2026, 10, 6)))
    with pytest.raises(OverlapConflict, match="Stay"):
        Stay.objects.create(room=room, nights=Range(dt.date(2026, 10, 3), dt.date(2026, 10, 5)))


def test_full_clean_reports_the_overlap_as_a_form_error(room: Room) -> None:
    from django.core.exceptions import ValidationError

    Reservation = _reservation_model()
    existing = Reservation.objects.create(room=room, during=span(0, 2))
    candidate = Reservation(room=room, during=span(1, 3))
    with pytest.raises(ValidationError) as raised:
        candidate.full_clean()
    assert f"E984: This overlaps Reservation {existing.pk}" in str(raised.value)
    Reservation(room=room, during=span(2, 3)).full_clean()  # free: no error

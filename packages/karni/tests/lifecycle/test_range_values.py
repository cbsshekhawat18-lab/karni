"""Range columns in factories, seeds and assert_crud: a valid range per row, never an overlap.

``karni make model ... during:datetimerange`` (or ``nights:daterange``) must
give a model that ``karni seed`` and its generated API test can fill. Every
test here needs PostgreSQL (range columns, EXCLUDE for no_overlap).
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient

from karni.seeding import seed
from karni.testing import assert_crud
from karni.testing.factories import create_batch
from tests.lifecycleapp.models import HAS_RANGES, Room

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="range columns need PostgreSQL"),
    pytest.mark.skipif(not HAS_RANGES, reason="range columns need psycopg"),
]

ROUTES = override_settings(
    ROOT_URLCONF="tests.lifecycleapp.urls",
    KARNI_API_ROUTER="tests.lifecycle.test_range_values.router",
)


def router() -> object:
    from rest_framework.routers import DefaultRouter

    from tests.lifecycleapp import viewsets

    found = DefaultRouter()
    found.register("reservations", viewsets.ReservationViewSet, basename="reservation")
    return found


@pytest.fixture
def routes() -> Iterator[None]:
    with ROUTES:
        yield


def test_factories_fill_required_ranges_that_never_overlap() -> None:
    from tests.lifecycleapp.models import Reservation, Stay

    room = Room.objects.create(name="Blue")
    # Both models forbid overlaps per room: one clash would be an IntegrityError.
    reservations = create_batch(Reservation, 6, room=room)
    stays = create_batch(Stay, 6, room=room)
    for row in reservations:
        assert isinstance(row.during.lower, dt.datetime)
        assert row.during.lower < row.during.upper and row.during.bounds == "[)"
    for stay in stays:
        assert isinstance(stay.nights.lower, dt.date)
        assert stay.nights.lower < stay.nights.upper
    assert Reservation.objects.filter(room=room).count() == 6


def test_seed_fills_range_columns_row_by_row_and_in_bulk() -> None:
    from tests.lifecycleapp.models import Reservation, Stay

    labels = ["lifecycleapp.Room", "lifecycleapp.Reservation", "lifecycleapp.Stay"]
    report = seed(models=labels, count=5)
    assert report.rows["lifecycleapp.Reservation"] == 5
    assert report.rows["lifecycleapp.Stay"] == 5
    bulk = seed(models=labels, volume=60, batch_size=20, reset=True)
    assert bulk.rows["lifecycleapp.Reservation"] == 60
    ranges = Reservation.objects.values_list("during", flat=True)
    assert all(row.lower < row.upper for row in ranges)
    assert Stay.objects.count() == 60


def test_assert_crud_sends_and_compares_a_range(routes: None) -> None:
    from tests.lifecycleapp.viewsets import ReservationViewSet

    report = assert_crud(ReservationViewSet)
    assert not report.failures
    assert {"create", "update"} <= set(report.passed)


def test_a_multipart_form_may_send_a_range_as_json_text() -> None:
    """@karni/ui sends an object in a multipart body as JSON text (contract D2)."""
    room = Room.objects.create(name="Red")
    user = get_user_model().objects.create_user(email="r@example.com", password="x-Password-1")
    client = APIClient()
    client.force_authenticate(user)
    start = dt.datetime(2026, 10, 21, 10, tzinfo=dt.UTC)
    during = {"lower": start.isoformat(), "upper": (start + dt.timedelta(hours=1)).isoformat()}
    with override_settings(ROOT_URLCONF="tests.lifecycleapp.urls"):
        response = client.post(
            "/api/reservations/",
            {"room": str(room.pk), "during": json.dumps(during)},
            format="multipart",
        )
        assert response.status_code == 201, response.content
        assert response.json()["during"]["bounds"] == "[)"
        bad = client.post(
            "/api/reservations/", {"room": str(room.pk), "during": "{not json"}, format="multipart"
        )
    assert bad.status_code == 400 and "during" in bad.json()

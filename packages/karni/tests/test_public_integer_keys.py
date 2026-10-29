"""karni.W530 (experimental): anyone may read a resource whose integer ids can be guessed.

Integer keys are sequential. A resource whose read access admits anonymous
callers and whose detail route looks rows up by that key lets a visitor count
the rows and walk the detail URLs. The check stays silent for UUID keys, a
slug lookup, a read access that turns anonymous callers away, and a viewset
marked ``# karni: allow(public-integer-key): <reason>``.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings

from karni.api.access import Access, Authenticated, HasRole, Public
from karni.api.routers import KarniRouter
from karni.api.viewsets import BaseViewSet
from karni.checks import check_public_integer_keys, has_integer_key
from karni.errorcodes import docs_url
from tests.testapp.models import Entry, Part, Reading, Shelf, Stamp

pytestmark = pytest.mark.django_db


class PublicPartViewSet(BaseViewSet):
    model = Part
    access = Access(read=Public(), write=HasRole("staff"))


class PublicReadingViewSet(BaseViewSet):
    model = Reading
    access = Access(read=Public() | HasRole("staff"), write=HasRole("staff"))


class SlugPartViewSet(BaseViewSet):
    """Looked up by the part number: the ids are not in the URL."""

    model = Part
    lookup_field = "number"
    access = Access(read=Public(), write=HasRole("staff"))


class SignedInPartViewSet(BaseViewSet):
    model = Part
    access = Access(read=Authenticated(), write=HasRole("staff"))


class PublicShelfViewSet(BaseViewSet):
    """A UUID key: nothing to guess."""

    model = Shelf
    access = Access(read=Public(), write=HasRole("staff"))


# karni: allow(public-integer-key): part numbers and ids are printed in the public catalogue
class MarkedPartViewSet(BaseViewSet):
    model = Part
    access = Access(read=Public(), write=HasRole("staff"))


# karni: allow(public-integer-key):
class ReasonlessPartViewSet(BaseViewSet):
    model = Part
    access = Access(read=Public(), write=HasRole("staff"))


def public_router() -> Any:
    router = KarniRouter()
    router.register("parts", PublicPartViewSet, basename="w530-parts")
    router.register("readings", PublicReadingViewSet, basename="w530-readings")
    return router


def quiet_router() -> Any:
    router = KarniRouter()
    for prefix, viewset in (
        ("slug-parts", SlugPartViewSet),
        ("signed-in-parts", SignedInPartViewSet),
        ("shelves", PublicShelfViewSet),
        ("marked-parts", MarkedPartViewSet),
    ):
        router.register(prefix, viewset, basename=f"w530-{prefix}")
    return router


def reasonless_router() -> Any:
    router = KarniRouter()
    router.register("reasonless-parts", ReasonlessPartViewSet, basename="w530-reasonless")
    return router


def test_has_integer_key() -> None:
    assert has_integer_key(Part) and has_integer_key(Entry)  # BigIntBaseModel, BigAutoField
    assert not has_integer_key(Stamp) and not has_integer_key(Shelf)  # UUIDs


@override_settings(KARNI_API_ROUTER="tests.test_public_integer_keys.public_router")
def test_a_public_resource_on_integer_keys_warns() -> None:
    messages = check_public_integer_keys()
    assert [(m.id, m.obj) for m in messages] == [
        ("karni.W530", PublicPartViewSet),
        ("karni.W530", PublicReadingViewSet),
    ]
    first = messages[0]
    assert first.msg.startswith("PublicPartViewSet lets anyone read Part rows by an integer id")
    assert "/parts/1/, /parts/2/" in first.msg
    assert "UUID key" in first.hint and 'lookup_field = "slug"' in first.hint
    assert "allow(public-integer-key)" in first.hint
    assert first.hint.endswith(f"See {docs_url('W530')}")


@override_settings(KARNI_API_ROUTER="tests.test_public_integer_keys.quiet_router")
def test_uuid_keys_slug_lookups_signed_in_reads_and_marked_viewsets_are_quiet() -> None:
    assert check_public_integer_keys() == []


@override_settings(KARNI_API_ROUTER="tests.test_public_integer_keys.reasonless_router")
def test_a_marker_without_a_reason_does_not_silence_it() -> None:
    (message,) = check_public_integer_keys()
    assert message.obj is ReasonlessPartViewSet
    assert "has no reason, so it does not silence this" in message.msg


@override_settings(
    KARNI_API_ROUTER="tests.test_public_integer_keys.public_router",
    SILENCED_SYSTEM_CHECKS=["karni.W530"],
)
def test_silenced_for_the_project_through_django() -> None:
    messages = check_public_integer_keys()
    assert messages and all(message.is_silenced() for message in messages)


@override_settings(KARNI_API_ROUTER="nowhere.get_router")
def test_an_unimportable_router_is_left_to_e128() -> None:
    assert check_public_integer_keys() == []

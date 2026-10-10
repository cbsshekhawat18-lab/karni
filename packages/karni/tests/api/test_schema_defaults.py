"""Model defaults reach the OpenAPI schema, so a form can start from them."""

from __future__ import annotations

import pytest
from drf_spectacular.generators import SchemaGenerator

pytestmark = pytest.mark.django_db


def _request_properties(component: str) -> dict:
    schema = SchemaGenerator().get_schema(request=None, public=True)
    return schema["components"]["schemas"][component]["properties"]


def test_plain_model_defaults_are_published_on_the_request_schema() -> None:
    event = _request_properties("TestappEventRequest")
    assert event["is_public"]["default"] is True
    assert "default" not in event["title"]  # no model default


def test_callable_and_read_only_defaults_are_left_out() -> None:
    event = _request_properties("TestappEventRequest")
    assert "status" not in event  # read-only via APIMeta: not writable at all
    assert "default" not in _request_properties("TestappVenueRequest").get("id", {})

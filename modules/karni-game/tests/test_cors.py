"""A portal build calls the game API from another origin, with a token and never a cookie."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from karni_game import checks
from tests.conftest import Guest

PORTAL = "https://games.portal.example"


def preflight(path: str, origin: str = PORTAL) -> Any:
    return APIClient().options(
        path,
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="x-player-token, content-type",
    )


def test_a_listed_origin_may_call_the_game_api_with_a_token(guest: Guest) -> None:
    answer = preflight("/api/game/block-hopper/boards/high/scores/")
    assert answer.status_code == 200
    assert answer["Access-Control-Allow-Origin"] == PORTAL
    allowed = answer["Access-Control-Allow-Headers"].lower()
    assert "x-player-token" in allowed and "authorization" in allowed
    assert "content-type" in allowed
    assert "Access-Control-Allow-Credentials" not in answer
    me = guest.client.get("/api/game/me/", HTTP_ORIGIN=PORTAL)
    assert me.status_code == 200
    assert me["Access-Control-Allow-Origin"] == PORTAL


def test_other_origins_and_other_paths_get_nothing(guest: Guest) -> None:
    assert "Access-Control-Allow-Origin" not in preflight(
        "/api/game/guest/", "https://evil.example"
    )
    assert "Access-Control-Allow-Origin" not in preflight("/api/game-players/")
    assert "Access-Control-Allow-Origin" not in preflight("/api/auth/login/")
    with override_settings(KARNI_GAME_CORS_ORIGINS=["*"]):
        assert (
            preflight("/api/game/guest/", "https://any.example")["Access-Control-Allow-Origin"]
            == "https://any.example"
        )
    with override_settings(KARNI_GAME_CORS_ORIGINS=[]):
        assert "Access-Control-Allow-Origin" not in preflight("/api/game/guest/")


def test_across_origins_an_account_signs_in_with_its_jwt_never_a_cookie(
    make_account: Callable[..., Any], game: Any
) -> None:
    user = make_account("ines@example.com")
    session = APIClient()
    session.force_login(user)  # a real session cookie, through the authenticators
    assert session.get("/api/game/me/").data["guest"] is False  # the same origin
    across = session.get("/api/game/me/", HTTP_ORIGIN=PORTAL)
    assert (across.status_code, across.data["code"]) == (401, "GAME002")
    bearer = APIClient()
    bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    answer = bearer.get("/api/game/me/", HTTP_ORIGIN=PORTAL)
    assert answer.status_code == 200 and answer.data["guest"] is False


def test_game038_when_the_browser_could_not_send_the_token() -> None:
    assert checks.run_checks() == []
    with override_settings(CORS_ALLOW_HEADERS=("content-type", "authorization")):
        (failure,) = checks.run_checks()
    assert failure.startswith("GAME038") and "x-player-token" in failure
    with override_settings(KARNI_GAME_CORS_ORIGINS=[], CORS_ALLOW_HEADERS=()):
        assert checks.run_checks() == []

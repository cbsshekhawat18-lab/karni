"""The realtime server contract: a short-lived signed player token, and a signed results report."""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from karni_game import multiplayer
from karni_game.models import Board, Currency, Game, Match, Player, Reward, Score, Wallet
from karni_game.signatures import sign
from tests.conftest import Guest

SECRET = "karni-game-tests-realtime-server-shared-secret"
PATH = "/api/game/block-hopper/multiplayer/"


@pytest.fixture
def arena(game: Game) -> Board:
    coins = Currency.objects.create(game=game, key="coins", title="Coins")
    Reward.objects.create(
        game=game, key="match-win", title="Win", kind="match", currency=coins, amount=40
    )
    return Board.objects.create(game=game, key="arena", title="Arena", max_value=10_000)


def test_the_token_names_the_player_for_the_game_server(guest: Guest, game: Game) -> None:
    answer = guest.post(f"{PATH}token/")
    assert answer.status_code == 201, answer.content
    claims = jwt.decode(
        answer.data["token"],
        SECRET,
        algorithms=["HS256"],
        audience="game:block-hopper",
        issuer="karni-game",
    )
    assert claims["sub"] == guest.player_id
    assert (claims["name"], claims["guest"]) == ("Swift Fox", True)
    assert claims["exp"] - claims["iat"] == 300
    assert claims["jti"]
    assert answer.data["player"] == {"id": guest.player_id, "handle": "Swift Fox"}
    assert multiplayer.verify_token(answer.data["token"], game)["sub"] == guest.player_id


def test_a_token_is_for_one_game_and_expires(guest: Guest, game: Game) -> None:
    token = guest.post(f"{PATH}token/").data["token"]
    other = Game.objects.create(slug="tile-match", title="Tile Match")
    with pytest.raises(jwt.InvalidAudienceError):
        multiplayer.verify_token(token, other)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token,
            "another-secret-of-thirty-two-bytes-at-least",
            algorithms=["HS256"],
            audience="game:block-hopper",
        )
    with override_settings(KARNI_GAME_TOKEN_SECONDS=-10):
        old = guest.post(f"{PATH}token/").data["token"]
    with pytest.raises(jwt.ExpiredSignatureError):
        multiplayer.verify_token(old, game)


def test_no_token_without_a_secret_or_for_a_banned_player(guest: Guest, game: Game) -> None:
    with override_settings(KARNI_GAME_SERVER_SECRET=""):
        answer = guest.post(f"{PATH}token/")
    assert (answer.status_code, answer.data["code"]) == (503, "GAME027")
    Player.objects.filter(pk=guest.player_id).update(banned_at=timezone.now())
    assert guest.post(f"{PATH}token/").data["code"] == "GAME029"


def report(body: dict[str, Any], secret: str = SECRET, **stamp: Any) -> Any:
    raw = json.dumps(body).encode()
    headers = sign(secret, raw, **stamp)
    return APIClient().post(
        f"{PATH}results/",
        raw,
        content_type="application/json",
        **{f"HTTP_{name.upper().replace('-', '_')}": value for name, value in headers.items()},
    )


def test_a_report_feeds_scores_and_rewards_once(guest: Guest, other: Guest, arena: Board) -> None:
    body = {
        "match": "arena-0042",
        "results": [
            {"player": guest.player_id, "board": "arena", "value": 1200, "rewards": ["match-win"]},
            {"player": other.player_id, "board": "arena", "value": 900},
        ],
    }
    answer = report(body)
    assert answer.status_code == 200, answer.content
    assert answer.data == {"match": "arena-0042", "recorded": 2, "duplicate": False}
    entries = guest.get("/api/game/block-hopper/boards/arena/").data["entries"]
    assert [(row["handle"], row["value"]) for row in entries] == [
        ("Swift Fox", 1200),
        ("Quiet Owl", 900),
    ]
    assert Wallet.objects.get(player_id=guest.player_id).balance == 40
    assert Score.objects.filter(source="match").count() == 2
    assert report(body).data == {"match": "arena-0042", "recorded": 0, "duplicate": True}
    assert Wallet.objects.get(player_id=guest.player_id).balance == 40


def test_a_report_is_whole_or_nothing(guest: Guest, arena: Board) -> None:
    bad_rows = [
        [{"player": "8b4e0000-0000-0000-0000-000000000000", "board": "arena", "value": 1}],
        [{"player": guest.player_id, "board": "nope", "value": 1}],
        [{"player": guest.player_id, "rewards": ["nope"]}],
    ]
    for rows in bad_rows:
        answer = report({"match": "m-1", "results": rows})
        assert (answer.status_code, answer.data["code"], answer.data["index"]) == (
            400,
            "GAME035",
            0,
        )
    out_of_range = report(
        {
            "match": "m-2",
            "results": [
                {"player": guest.player_id, "rewards": ["match-win"]},
                {"player": guest.player_id, "board": "arena", "value": 99_999},
            ],
        }
    )
    assert out_of_range.data["code"] == "GAME013"
    assert not Match.objects.exists()
    assert not Wallet.objects.filter(balance__gt=0).exists()


def test_a_report_must_be_signed(guest: Guest, arena: Board) -> None:
    body = {"match": "m-3", "results": [{"player": guest.player_id, "rewards": ["match-win"]}]}
    assert report(body, secret="wrong").data["code"] == "GAME019"
    stale = report(body, timestamp=int(time.time()) - 900)
    assert (stale.status_code, stale.data["code"]) == (403, "GAME019")
    # A player's own client cannot report: it has no secret, and its token is no signature.
    token = guest.post(f"{PATH}token/").data["token"]
    client = APIClient()
    client.credentials(HTTP_X_PLAYER_TOKEN=guest.token, HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.post(f"{PATH}results/", body, format="json").data["code"] == "GAME019"
    assert not Match.objects.exists()


def test_a_banned_players_score_is_left_out(guest: Guest, arena: Board) -> None:
    Player.objects.filter(pk=guest.player_id).update(banned_at=timezone.now())
    body = {"match": "m-4", "results": [{"player": guest.player_id, "board": "arena", "value": 5}]}
    assert report(body).data["recorded"] == 1
    assert not Score.objects.exists()

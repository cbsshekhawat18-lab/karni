"""Remote config and feature flags in one call, and analytics through the family events."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings
from karni.testing import capture_events

from karni_game import config
from karni_game.models import ConfigValue, Game, Player
from tests.conftest import Guest

GAME = "/api/game/block-hopper/"


@pytest.fixture
def values(game: Game) -> None:
    ConfigValue.objects.create(game=game, key="jump_height", value=3.5)
    ConfigValue.objects.create(game=game, key="levels", value=["meadow", "cave"])
    ConfigValue.objects.create(game=game, key="night_mode", flag=True, value=True)
    ConfigValue.objects.create(game=game, key="new_shop", flag=True, value=False)
    ConfigValue.objects.create(game=game, key="half", flag=True, value=True, rollout=50)


def test_the_one_call_holds_config_and_flags(api: Any, values: None) -> None:
    answer = api.get(GAME)
    assert answer.data["config"] == {"jump_height": 3.5, "levels": ["meadow", "cave"]}
    assert answer.data["flags"] == {"half": False, "new_shop": False, "night_mode": True}


def test_a_rollout_is_on_for_the_same_share_of_players(
    make_guest: Any, game: Game, values: None
) -> None:
    with override_settings(KARNI_GAME_RATES={"guest": None}):
        guests = [make_guest() for _ in range(40)]
    on = [guest.get(GAME).data["flags"]["half"] for guest in guests]
    assert 5 < sum(on) < 35
    # The same players every time.
    assert on == [guest.get(GAME).data["flags"]["half"] for guest in guests]
    player = Player.objects.get(pk=guests[0].player_id)
    assert config.bucket(player, "half") == config.bucket(player, "half")


def test_config_is_per_game(api: Any, values: None) -> None:
    Game.objects.create(slug="tile-match", title="Tile Match")
    assert api.get("/api/game/tile-match/").data["config"] == {}


@pytest.fixture
def analytics(game: Game) -> Game:
    game.settings = {
        "analytics": {
            "level_started": {"level": "int"},
            "level_done": {"level": "int", "ms": "int", "mode": "str", "perfect": "bool"},
        }
    }
    game.save()
    return game


def test_declared_events_are_published(guest: Guest, analytics: Game) -> None:
    body = {
        "events": [
            {"name": "level_started", "props": {"level": 3}},
            {"name": "level_done", "props": {"level": 3, "ms": 52000, "perfect": True}},
        ]
    }
    with capture_events() as published:
        answer = guest.post(f"{GAME}events/", body)
    assert answer.status_code == 202, answer.content
    assert answer.data == {"accepted": 2, "rejected": []}
    published.assert_published("game.analytics.tracked", event="level_started", count=1)
    published.assert_published(
        "game.analytics.tracked",
        event="level_done",
        props={"level": 3, "ms": 52000, "perfect": True},
    )


def test_undeclared_events_and_props_are_refused(guest: Guest, analytics: Game) -> None:
    body = {
        "events": [
            {"name": "level_started", "props": {"level": 1}},
            {"name": "bought_gems", "props": {}},
            {"name": "level_started", "props": {"level": "three"}},
            {"name": "level_started", "props": {"secret": 1}},
            {"name": "level_done", "props": {"mode": "x" * 101}},
            {"name": "level_started", "props": {"level": True}},
        ]
    }
    answer = guest.post(f"{GAME}events/", body)
    assert answer.status_code == 202
    assert answer.data["accepted"] == 1
    assert [row["index"] for row in answer.data["rejected"]] == [1, 2, 3, 4, 5]
    assert {row["code"] for row in answer.data["rejected"]} == {"GAME025"}
    none = guest.post(f"{GAME}events/", {"events": [{"name": "bought_gems"}]})
    assert (none.status_code, none.data["code"]) == (400, "GAME025")


def test_events_need_no_player_and_are_limited(api: Any, analytics: Game) -> None:
    body = {"events": [{"name": "level_started", "props": {"level": 1}}]}
    assert api.post(f"{GAME}events/", body, format="json").status_code == 202
    with override_settings(KARNI_GAME_RATES={"events": "1/min"}):
        api.post(f"{GAME}events/", body, format="json")
        answer = api.post(f"{GAME}events/", body, format="json")
    assert answer.data["code"] == "GAME015"
    too_many = {"events": [{"name": "level_started"}] * 21}
    assert api.post(f"{GAME}events/", too_many, format="json").status_code == 400


def test_the_game_refuses_an_analytics_schema_it_cannot_read(game: Game) -> None:
    from django.core.exceptions import ValidationError

    game.settings = {"analytics": {"level_done": {"level": "date"}}}
    with pytest.raises(ValidationError, match="GAME026"):
        game.save()
    game.settings = {"analytics": {"bad name!": {}}}
    with pytest.raises(ValidationError, match="GAME026"):
        game.save()

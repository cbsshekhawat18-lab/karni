"""Saves: versioned JSON per player, game and slot, with a server version counter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone
from karni import people
from karni.exceptions import KarniImproperlyConfigured

from karni_game import hooks, saves
from karni_game.models import Game, Player, Save
from tests.conftest import Guest, signed_in

PATH = "/api/game/block-hopper/saves/"


def put(guest: Guest, slot: str, data: Any, base: int, schema: int = 1) -> Any:
    return guest.put(
        f"{PATH}{slot}/", {"data": data, "schema_version": schema, "base_version": base}
    )


def test_a_save_is_written_read_and_versioned(guest: Guest, game: Game) -> None:
    first = put(guest, "main", {"level": 1}, 0)
    assert first.status_code == 200, first.content
    assert (first.data["version"], first.data["data"]) == (1, {"level": 1})
    second = put(guest, "main", {"level": 2}, 1)
    assert second.data["version"] == 2
    read = guest.get(f"{PATH}main/")
    assert read.status_code == 200
    assert read.data["data"] == {"level": 2}
    assert read.data["size"] == len('{"level":2}')
    listed = guest.get(PATH)
    assert listed.data["max_slots"] == 5
    assert [row["slot"] for row in listed.data["results"]] == ["main"]
    assert "data" not in listed.data["results"][0]


def test_a_stale_write_is_game008_with_the_server_copy(guest: Guest, game: Game) -> None:
    put(guest, "main", {"level": 1}, 0)
    put(guest, "main", {"level": 5}, 1)  # another device
    stale = put(guest, "main", {"level": 2}, 1)
    assert (stale.status_code, stale.data["code"]) == (409, "GAME008")
    assert stale.data["save"]["version"] == 2
    assert stale.data["save"]["data"] == {"level": 5}
    created_twice = put(guest, "main", {"level": 9}, 0)
    assert created_twice.data["code"] == "GAME008"
    gone = put(guest, "other", {"level": 9}, 3)
    assert (gone.data["code"], gone.data["save"]) == ("GAME008", None)
    assert Save.objects.get(slot="main").data == {"level": 5}


def test_a_save_has_a_size_limit(guest: Guest, game: Game) -> None:
    game.settings = {"max_save_bytes": 256}
    game.save()
    answer = put(guest, "main", {"blob": "x" * 300}, 0)
    assert (answer.status_code, answer.data["code"]) == (413, "GAME007")
    assert answer.data["max_bytes"] == 256


def test_slots_are_named_and_counted(guest: Guest, game: Game) -> None:
    game.settings = {"max_slots": 2}
    game.save()
    assert put(guest, "Main Slot", {}, 0).data["code"] == "GAME011"
    put(guest, "one", {}, 0)
    put(guest, "two", {}, 0)
    answer = put(guest, "three", {}, 0)
    assert (answer.status_code, answer.data["code"]) == (400, "GAME011")
    assert put(guest, "one", {"again": True}, 1).status_code == 200


def test_data_is_a_json_object(guest: Guest, game: Game) -> None:
    answer = put(guest, "main", [1, 2, 3], 0)
    assert answer.status_code == 400
    assert "data" in answer.data


def test_a_save_is_deleted_at_its_version(guest: Guest, game: Game) -> None:
    put(guest, "main", {"level": 1}, 0)
    stale = guest.delete(f"{PATH}main/?base_version=7")
    assert stale.data["code"] == "GAME008"
    assert guest.delete(f"{PATH}main/?base_version=1").status_code == 204
    assert guest.get(f"{PATH}main/").status_code == 404
    assert guest.delete(f"{PATH}main/").status_code == 404
    # The slot is free again and starts at version 1.
    assert put(guest, "main", {"level": 3}, 0).data["version"] == 1


def test_an_older_save_is_migrated_on_read_and_on_write(guest: Guest, game: Game) -> None:
    put(guest, "main", {"level": 3}, 0)

    @hooks.save_migration("block-hopper", 1)
    def levels(data: dict[str, Any]) -> dict[str, Any]:
        return {"levels": list(range(1, data.pop("level", 0) + 1))}

    game.settings = {"save_schema_version": 2}
    game.save()
    read = guest.get(f"{PATH}main/")
    assert read.data["schema_version"] == 2
    assert read.data["data"] == {"levels": [1, 2, 3]}
    assert read.data["version"] == 2
    # An old client writes version 1: the server stores version 2.
    written = put(guest, "main", {"level": 1}, 2, schema=1)
    assert (written.data["schema_version"], written.data["data"]) == (2, {"levels": [1]})
    ahead = put(guest, "main", {}, 3, schema=3)
    assert (ahead.status_code, ahead.data["code"]) == (400, "GAME009")


def test_a_missing_migration_is_game010(game: Game, guest: Guest) -> None:
    game.settings = {"save_schema_version": 3}
    game.save()
    with pytest.raises(KarniImproperlyConfigured, match="GAME010"):
        saves.migrate(game, {}, 1)
    with pytest.raises(KarniImproperlyConfigured, match="GAME032"):
        hooks.save_migration("block-hopper", 0)

    @hooks.save_migration("block-hopper", 1)
    def first(data: dict[str, Any]) -> dict[str, Any]:
        return data

    with pytest.raises(KarniImproperlyConfigured, match="GAME032"):

        @hooks.save_migration("block-hopper", 1)
        def again(data: dict[str, Any]) -> dict[str, Any]:
            return data


def test_another_player_never_reaches_a_save(guest: Guest, other: Guest, game: Game) -> None:
    put(guest, "main", {"level": 7}, 0)
    assert other.get(f"{PATH}main/").status_code == 404
    assert other.get(PATH).data["results"] == []
    assert other.delete(f"{PATH}main/").status_code == 404
    # The same slot name is the other player's own slot.
    assert put(other, "main", {"level": 1}, 0).data["version"] == 1
    assert guest.get(f"{PATH}main/").data["data"] == {"level": 7}


def test_games_keep_their_saves_apart(guest: Guest, game: Game) -> None:
    Game.objects.create(slug="tile-match", title="Tile Match")
    put(guest, "main", {"level": 7}, 0)
    assert guest.get("/api/game/tile-match/saves/main/").status_code == 404


def test_saves_are_limited(guest: Guest, game: Game) -> None:
    with override_settings(KARNI_GAME_RATES={"save": "1/min"}):
        put(guest, "main", {}, 0)
        answer = put(guest, "main", {}, 1)
    assert (answer.status_code, answer.data["code"]) == (429, "GAME015")


def test_no_player_reaches_saves(api: Any, game: Game) -> None:
    assert api.get(PATH).data["code"] == "GAME002"
    answer = api.put(
        f"{PATH}main/", {"data": {}, "schema_version": 1, "base_version": 0}, format="json"
    )
    assert answer.data["code"] == "GAME002"


def test_a_guest_who_signs_in_keeps_both_copies_of_a_slot(
    guest: Guest, game: Game, make_account: Callable[..., Any]
) -> None:
    account = make_account("ines@example.com")
    mine = signed_in(account)
    mine.put(
        f"{PATH}main/",
        {"data": {"from": "account"}, "schema_version": 1, "base_version": 0},
        format="json",
    )
    mine.put(
        f"{PATH}cave/",
        {"data": {"from": "account"}, "schema_version": 1, "base_version": 0},
        format="json",
    )
    Save.objects.filter(slot__in=["main", "cave"]).update(
        updated_at=timezone.now() - timedelta(hours=1)
    )
    put(guest, "main", {"from": "guest"}, 0)
    put(guest, "extra", {"from": "guest"}, 0)
    answer = mine.post("/api/game/upgrade/", {"guest_token": guest.token}, format="json")
    assert answer.status_code == 200, answer.content
    assert answer.data["merged"]["saves"] == {"moved": 1, "kept_both": ["main"]}
    rows = {row["slot"]: row for row in mine.get(PATH).data["results"]}
    assert set(rows) == {"main", "main-merged", "cave", "extra"}
    assert mine.get(f"{PATH}main/").data["data"] == {"from": "guest"}
    assert mine.get(f"{PATH}main-merged/").data["data"] == {"from": "account"}


def test_erasing_the_person_drops_the_saves(guest: Guest, game: Game) -> None:
    put(guest, "main", {"name": "Ana"}, 0)
    player = Player.objects.get(pk=guest.player_id)
    people.erase(player.person)
    row = Save._base_manager.get(player=player)
    assert row.data == {} and row.deleted_at is not None


def test_staff_read_saves_and_cannot_write_them(
    guest: Guest, game: Game, make_account: Callable[..., Any]
) -> None:
    put(guest, "main", {"level": 1}, 0)
    manager = signed_in(make_account("boss@example.com", "game-manager"))
    listed = manager.get("/api/game-saves/")
    assert listed.status_code == 200
    row = listed.data["results"][0]
    assert (
        manager.patch(f"/api/game-saves/{row['id']}/", {"data": {}}, format="json").status_code
        == 405
    )
    customer = signed_in(make_account("ana@example.com"))
    assert customer.get("/api/game-saves/").status_code == 403

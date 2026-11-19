"""Players: a guest token the server issues, an account's player, and a guest who signs in."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from karni import people, preferences
from karni.people.models import Person
from karni.testing import capture_events
from karni.vetoes import register_veto, unregister_veto

from karni_game import checks, players
from karni_game.models import Game, Player
from tests.conftest import Guest, signed_in

MakeGuest = Callable[..., Guest]


def test_a_guest_is_a_person_without_an_account(make_guest: MakeGuest) -> None:
    with capture_events() as published:
        guest = make_guest("Swift Fox")
    player = Player.objects.select_related("person").get(pk=guest.player_id)
    assert player.handle == "Swift Fox"
    assert player.person.user_id is None
    assert player.person.source == "karni_game"
    assert player.is_guest
    # Only the hash of the token is stored.
    assert guest.token.startswith("gt_")
    assert player.token_hash == players.token_hash(guest.token)
    assert guest.token not in player.token_hash
    published.assert_published("game.player.joined", subject=player, guest=True)


def test_a_guest_without_a_handle_gets_one(api: Any) -> None:
    answer = api.post("/api/game/guest/", {}, format="json")
    assert answer.status_code == 201
    assert answer.data["player"]["handle"].startswith("Player ")
    assert answer.data["player"]["guest"] is True


def test_the_token_finds_the_guest(guest: Guest) -> None:
    answer = guest.get("/api/game/me/")
    assert answer.status_code == 200
    assert answer.data["id"] == guest.player_id
    assert answer.data["guest"] is True


def test_no_player_is_game002(api: Any) -> None:
    answer = api.get("/api/game/me/")
    assert answer.status_code == 401
    assert answer.data["code"] == "GAME002"
    assert answer.data["detail"].startswith("GAME002: ")


def test_an_unknown_token_is_game003(api: Any) -> None:
    api.credentials(HTTP_X_PLAYER_TOKEN="gt_not-a-real-token")
    answer = api.get("/api/game/me/")
    assert (answer.status_code, answer.data["code"]) == (401, "GAME003")


def test_a_handle_is_changed_and_checked(guest: Guest) -> None:
    answer = guest.patch("/api/game/me/", {"handle": "  Brave   Lynx "})
    assert answer.status_code == 200
    assert answer.data["handle"] == "Brave Lynx"
    refused = guest.patch("/api/game/me/", {"handle": "<script>"})
    assert refused.status_code == 400
    assert "handle" in refused.data


def test_a_verified_account_plays_with_its_person(make_account: Callable[..., Any]) -> None:
    account = make_account("noor@example.com")
    with capture_events() as published:
        answer = signed_in(account).get("/api/game/me/")
    assert answer.status_code == 200
    assert answer.data["guest"] is False
    player = Player.objects.get(pk=answer.data["id"])
    assert player.person.user_id == account.pk
    published.assert_published("game.player.joined", guest=False)
    # The second call finds the same player.
    assert signed_in(account).get("/api/game/me/").data["id"] == answer.data["id"]


def test_an_unverified_account_has_no_player_yet(make_account: Callable[..., Any]) -> None:
    account = make_account("lena@example.com", verified=False)
    answer = signed_in(account).get("/api/game/me/")
    assert (answer.status_code, answer.data["code"]) == (403, "GAME004")
    assert not Player.objects.exists()


def test_guest_play_switched_off_is_game005(api: Any) -> None:
    with preferences.override(game={"allow_guests": False}):
        answer = api.post("/api/game/guest/", {}, format="json")
    assert (answer.status_code, answer.data["code"]) == (403, "GAME005")


def test_issuing_guests_is_limited_per_address(api: Any) -> None:
    with override_settings(KARNI_GAME_RATES={"guest": "2/hour"}):
        for _ in range(2):
            assert api.post("/api/game/guest/", {}, format="json").status_code == 201
        answer = api.post("/api/game/guest/", {}, format="json")
    assert (answer.status_code, answer.data["code"]) == (429, "GAME015")
    assert int(answer["Retry-After"]) == answer.data["retry_after"] > 0


def test_a_veto_refuses_a_change(guest: Guest) -> None:
    def no_changes(context: Any) -> str | None:
        return "Not while impersonating." if context.action == "partial_update" else None

    register_veto(no_changes, name="test-no-changes")
    try:
        answer = guest.patch("/api/game/me/", {"handle": "Brave Lynx"})
    finally:
        unregister_veto("test-no-changes")
    assert answer.status_code == 403
    assert Player.objects.get(pk=guest.player_id).handle == "Swift Fox"


# -- a game ----------------------------------------------------------------------------


def test_the_boot_call_describes_the_game(api: Any, game: Game) -> None:
    answer = api.get("/api/game/block-hopper/")
    assert answer.status_code == 200
    assert answer.data["game"] == {"slug": "block-hopper", "title": "Block Hopper"}
    assert answer.data["server"]["timezone"] == "UTC"
    assert answer.data["save"] == {"schema_version": 1, "max_bytes": 65536, "max_slots": 5}


def test_an_unknown_or_inactive_game_is_game006(api: Any, game: Game) -> None:
    assert api.get("/api/game/tile-match/").data["code"] == "GAME006"
    game.is_active = False
    game.save()
    answer = api.get("/api/game/block-hopper/")
    assert (answer.status_code, answer.data["code"]) == (404, "GAME006")


def test_a_game_refuses_settings_it_cannot_use() -> None:
    with pytest.raises(ValidationError, match="GAME026"):
        Game.objects.create(slug="tile-match", title="Tile Match", settings={"timezone": "Mars"})
    with pytest.raises(ValidationError, match="GAME026"):
        Game.objects.create(slug="tile-match", title="Tile Match", settings={"max_slots": 0})
    with pytest.raises(ValidationError, match="GAME026"):
        Game.objects.create(slug="guest", title="A path")
    with pytest.raises(ValidationError, match="KARNI_GAME_MAX_SAVE_BYTES"):
        Game.objects.create(
            slug="tile-match", title="Tile Match", settings={"max_save_bytes": 10**9}
        )


# -- upgrade ---------------------------------------------------------------------------


def test_a_guest_who_signs_in_keeps_their_player(
    guest: Guest, make_account: Callable[..., Any]
) -> None:
    account = make_account("ines@example.com")
    client = signed_in(account)
    client.credentials(HTTP_X_PLAYER_TOKEN=guest.token)
    with capture_events() as published:
        answer = client.post("/api/game/upgrade/", {}, format="json")
    assert answer.status_code == 200, answer.content
    assert answer.data["merged"]["adopted"] is True
    assert answer.data["player"]["id"] == guest.player_id
    assert answer.data["player"]["guest"] is False
    player = Player.objects.select_related("person").get(pk=guest.player_id)
    assert player.person.user_id == account.pk
    assert player.handle == "Swift Fox"
    # The guest's person was merged into the account's, and the token is revoked.
    assert Person._base_manager.filter(merged_into=player.person).count() == 1
    assert guest.get("/api/game/me/").data["code"] == "GAME003"
    assert signed_in(account).get("/api/game/me/").data["id"] == guest.player_id
    published.assert_published("game.player.upgraded", adopted=True)


def test_a_guest_joins_an_account_that_plays_already(
    guest: Guest, make_account: Callable[..., Any]
) -> None:
    account = make_account("ines@example.com")
    mine = signed_in(account).get("/api/game/me/").data["id"]
    answer = signed_in(account).post(
        "/api/game/upgrade/", {"guest_token": guest.token}, format="json"
    )
    assert answer.status_code == 200, answer.content
    assert answer.data["player"]["id"] == mine
    assert answer.data["merged"]["adopted"] is False
    dropped = Player._base_manager.get(pk=guest.player_id)
    assert dropped.deleted_at is not None
    assert dropped.token_hash == ""
    assert Player.objects.count() == 1


def test_an_upgrade_needs_an_account_and_a_guest(
    api: Any, guest: Guest, make_account: Callable[..., Any]
) -> None:
    api.credentials(HTTP_X_PLAYER_TOKEN=guest.token)
    assert api.post("/api/game/upgrade/", {}, format="json").data["code"] == "GAME002"
    account = make_account("ines@example.com")
    answer = signed_in(account).post("/api/game/upgrade/", {}, format="json")
    assert (answer.status_code, answer.data["code"]) == (409, "GAME028")
    unverified = make_account("mira@example.com", verified=False)
    client = signed_in(unverified)
    answer = client.post("/api/game/upgrade/", {"guest_token": guest.token}, format="json")
    assert answer.data["code"] == "GAME004"


def test_a_refused_merge_is_game028(guest: Guest, make_account: Callable[..., Any]) -> None:
    account = make_account("ines@example.com")
    refused = people.MergeRefused("Both have a profile.", code="E251")
    with mock.patch("karni.people.merge", side_effect=refused):
        answer = signed_in(account).post(
            "/api/game/upgrade/", {"guest_token": guest.token}, format="json"
        )
    assert (answer.status_code, answer.data["code"]) == (409, "GAME028")
    assert "Both have a profile." in answer.data["detail"]


# -- people ----------------------------------------------------------------------------


def test_erasing_the_person_anonymises_the_player(guest: Guest) -> None:
    player = Player.objects.get(pk=guest.player_id)
    people.erase(player.person)
    player.refresh_from_db()
    assert player.handle == "Erased player"
    assert player.token_hash == ""


def test_the_person_facts_know_when_they_played(guest: Guest) -> None:
    player = Player.objects.get(pk=guest.player_id)
    row = Person.objects.with_facts("game_last_seen").get(pk=player.person_id)
    assert row.game_last_seen == player.last_seen_at


# -- checks ----------------------------------------------------------------------------


def test_game001_without_the_people_contract() -> None:
    assert checks.people_installed() == []
    with mock.patch("karni_game.checks.apps.is_installed", return_value=False):
        (message,) = checks.people_installed()
    assert message.id == "karni.GAME001"


def test_game030_without_the_include() -> None:
    assert checks.run_checks() == []
    with override_settings(ROOT_URLCONF="karni.api.urls"):
        (failure,) = checks.run_checks()
        with mock.patch("karni_game.checks.apps.is_installed", return_value=False):
            assert checks.run_checks() == []  # installed in the interpreter, not in the project
    assert failure.startswith("GAME030")

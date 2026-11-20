"""The staff's side: the resources answer the roles' grants, never a player."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from karni_game.models import Player
from tests.conftest import Guest, signed_in


def test_a_moderator_bans_and_unbans_a_player(
    guest: Guest, make_account: Callable[..., Any]
) -> None:
    moderator = signed_in(make_account("mod@example.com", "game-moderator"))
    path = f"/api/game-players/{guest.player_id}/"
    assert moderator.get(path).status_code == 200
    answer = moderator.post(f"{path}ban/", {"reason": "Impossible scores"}, format="json")
    assert answer.status_code == 200, answer.content
    player = Player.objects.get(pk=guest.player_id)
    assert player.is_banned and player.ban_reason == "Impossible scores"
    assert moderator.post(f"{path}unban/", {}, format="json").status_code == 200
    assert not Player.objects.get(pk=guest.player_id).is_banned


def test_a_manager_revokes_a_guest_token(guest: Guest, make_account: Callable[..., Any]) -> None:
    manager = signed_in(make_account("boss@example.com", "game-manager"))
    path = f"/api/game-players/{guest.player_id}/revoke-token/"
    assert manager.post(path, {}, format="json").status_code == 200
    assert guest.get("/api/game/me/").data["code"] == "GAME003"


def test_a_player_reaches_no_staff_resource(guest: Guest, make_account: Callable[..., Any]) -> None:
    customer = signed_in(make_account("ana@example.com"))
    assert customer.get("/api/game-players/").status_code == 403
    assert customer.post(f"/api/game-players/{guest.player_id}/ban/", {}).status_code in (403, 404)
    assert customer.get("/api/games/").status_code == 403
    assert guest.get("/api/game-players/").status_code in (401, 403)
    assert not Player.objects.get(pk=guest.player_id).is_banned


def test_a_moderator_does_not_create_players(make_account: Callable[..., Any]) -> None:
    manager = signed_in(make_account("boss@example.com", "game-manager"))
    assert manager.post("/api/game-players/", {"handle": "x"}, format="json").status_code == 405

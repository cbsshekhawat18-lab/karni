"""The admin: games, boards, flagged runs, players with their person, wallets and ledgers, config,
achievements; and impersonation and erase as for any person."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from karni import people
from karni.vetoes import register_veto, unregister_veto

from karni_game import wallet
from karni_game.models import (
    Achievement,
    Board,
    ConfigValue,
    Currency,
    Game,
    Item,
    LedgerEntry,
    Player,
    Score,
    Wallet,
)
from tests.conftest import Guest

ADMIN = "/admin/karni_game/"


@pytest.fixture
def staff() -> Client:
    user = get_user_model().objects.create_superuser(
        email="root@example.com", password="karni-password"
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def board(game: Game) -> Board:
    return Board.objects.create(game=game, key="high", title="High", review_beyond=1000)


@pytest.fixture
def coins(game: Game) -> Currency:
    return Currency.objects.create(game=game, key="coins", title="Coins")


def test_every_screen_opens(staff: Client, game: Game, board: Board, coins: Currency) -> None:
    ConfigValue.objects.create(game=game, key="night_mode", flag=True, value=True)
    Achievement.objects.create(game=game, key="first", title="First", counter="runs")
    for name in (
        "game",
        "board",
        "player",
        "score",
        "wallet",
        "ledgerentry",
        "currency",
        "reward",
        "item",
        "achievement",
        "mission",
        "configvalue",
        "save",
        "streak",
    ):
        answer = staff.get(f"{ADMIN}{name}/")
        assert answer.status_code == 200, (name, answer.status_code)
    assert staff.get(f"{ADMIN}game/{game.pk}/change/").status_code == 200


def test_players_show_their_person_and_are_banned(staff: Client, guest: Guest) -> None:
    player = Player.objects.get(pk=guest.player_id)
    page = staff.get(f"{ADMIN}player/")
    assert player.handle in page.content.decode()
    staff.post(f"{ADMIN}player/", {"action": "ban", "_selected_action": [str(player.pk)]})
    assert Player.objects.get(pk=player.pk).is_banned
    staff.post(f"{ADMIN}player/", {"action": "unban", "_selected_action": [str(player.pk)]})
    assert not Player.objects.get(pk=player.pk).is_banned
    staff.post(f"{ADMIN}player/", {"action": "revoke_token", "_selected_action": [str(player.pk)]})
    assert guest.get("/api/game/me/").data["code"] == "GAME003"


def test_flagged_runs_are_accepted_or_rejected(staff: Client, guest: Guest, board: Board) -> None:
    held = guest.post("/api/game/block-hopper/boards/high/scores/", {"value": 5000})
    assert held.data["score"]["status"] == "flagged"
    flagged = staff.get(f"{ADMIN}score/?status__exact=flagged")
    assert flagged.status_code == 200
    score = Score.objects.get()
    staff.post(f"{ADMIN}score/", {"action": "accept", "_selected_action": [str(score.pk)]})
    assert Score.objects.get().status == "accepted"
    assert guest.get("/api/game/block-hopper/boards/high/").data["entries"][0]["value"] == 5000
    staff.post(f"{ADMIN}score/", {"action": "reject", "_selected_action": [str(score.pk)]})
    assert Score.objects.get().status == "rejected"
    assert guest.get("/api/game/block-hopper/boards/high/").data["entries"] == []


def test_currency_is_granted_with_a_note(staff: Client, guest: Guest, coins: Currency) -> None:
    player = Player.objects.get(pk=guest.player_id)
    row = wallet.wallet_of(player, coins)
    form = staff.post(
        f"{ADMIN}wallet/", {"action": "grant_currency", "_selected_action": [str(row.pk)]}
    )
    assert form.status_code == 200 and b"Grant" in form.content
    staff.post(
        f"{ADMIN}wallet/",
        {
            "action": "grant_currency",
            "_selected_action": [str(row.pk)],
            "apply": "1",
            "amount": "75",
            "note": "Sorry for the outage",
        },
    )
    assert Wallet.objects.get(pk=row.pk).balance == 75
    entry = LedgerEntry.objects.get()
    assert (entry.reason, entry.note) == ("grant", "Sorry for the outage")
    assert staff.get(f"{ADMIN}wallet/{row.pk}/change/").status_code == 200
    assert staff.get(f"{ADMIN}ledgerentry/{entry.pk}/change/").status_code in (200, 403)


def test_an_impersonator_is_refused_what_the_veto_blocks(
    game: Game, coins: Currency, make_account: Callable[..., Any]
) -> None:
    """karni-impersonation blocks deletes by default, and a project adds karni_game.*."""
    from tests.conftest import signed_in

    Item.objects.create(
        game=game, key="red-cap", title="Red cap", slot="hat", currency=coins, price=5
    )
    user = make_account("ines@example.com")
    client = signed_in(user)
    client.put(
        "/api/game/block-hopper/saves/main/",
        {"data": {}, "schema_version": 1, "base_version": 0},
        format="json",
    )
    wallet.change(Player.objects.get(person__user=user), coins, 10, reason="grant")

    def as_impersonating(context: Any) -> str | None:
        names = context.names()
        if "destroy" in names or any(name.startswith("karni_game.wallet") for name in names):
            return "Blocked while impersonating."
        return None

    register_veto(as_impersonating, name="test-impersonation")
    try:
        assert client.delete("/api/game/block-hopper/saves/main/").status_code == 403
        assert client.post("/api/game/block-hopper/shop/red-cap/buy/", {}).status_code == 403
        assert client.get("/api/game/block-hopper/saves/main/").status_code == 200
    finally:
        unregister_veto("test-impersonation")
    assert Wallet.objects.get().balance == 10


def test_staff_merging_two_people_merges_their_players(
    make_guest: Callable[..., Guest], game: Game, coins: Currency
) -> None:
    ana, ben = make_guest("Ana"), make_guest("Ben")
    keep, drop = Player.objects.get(pk=ana.player_id), Player.objects.get(pk=ben.player_id)
    wallet.change(keep, coins, 5, reason="grant")
    wallet.change(drop, coins, 7, reason="grant")
    people.merge(keep.person, drop.person)
    assert Wallet.objects.get(player=keep).balance == 12
    assert Player._base_manager.get(pk=drop.pk).deleted_at is not None

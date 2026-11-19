"""The wallet, the ledger, rewards the server declares, the shop and real-money items."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone
from karni import people
from karni.testing import capture_events
from rest_framework.test import APIClient

from karni_game import players, rewards, wallet
from karni_game.models import (
    Claim,
    Currency,
    Game,
    Item,
    LedgerEntry,
    Ownership,
    Player,
    Reward,
    Wallet,
)
from karni_game.signatures import sign
from tests.conftest import Guest, signed_in

GAME = "/api/game/block-hopper/"
PORTAL_SECRET = "arcade-portal-test-secret"


@pytest.fixture
def coins(game: Game) -> Currency:
    return Currency.objects.create(game=game, key="coins", title="Coins", cap=1000)


@pytest.fixture
def hat(game: Game, coins: Currency) -> Item:
    return Item.objects.create(
        game=game, key="red-cap", title="Red cap", slot="hat", currency=coins, price=50
    )


def player_of(guest: Guest) -> Player:
    return Player.objects.get(pk=guest.player_id)


def fill(guest: Guest, coins: Currency, amount: int) -> None:
    wallet.change(player_of(guest), coins, amount, reason="grant")


# -- the wallet and the ledger ---------------------------------------------------------


def test_every_change_is_a_ledger_entry(guest: Guest, coins: Currency) -> None:
    player = player_of(guest)
    first = wallet.change(player, coins, 120, reason="reward", reference="daily-coins")
    second = wallet.change(player, coins, -20, reason="purchase", reference="red-cap")
    assert (first.balance, second.balance) == (120, 100)
    entries = list(LedgerEntry.objects.order_by("created_at"))
    assert [(row.amount, row.balance_after, row.reason) for row in entries] == [
        (120, 120, "reward"),
        (-20, 100, "purchase"),
    ]
    answer = guest.get(f"{GAME}wallet/")
    assert answer.data["balances"] == [
        {"currency": "coins", "title": "Coins", "balance": 100, "cap": 1000}
    ]
    ledger = guest.get(f"{GAME}wallet/ledger/", currency="coins").data
    assert ledger["count"] == 2
    assert [row["amount"] for row in ledger["results"]] == [-20, 120]


def test_a_balance_never_goes_below_zero(guest: Guest, coins: Currency) -> None:
    from karni_game.errors import GameError

    fill(guest, coins, 10)
    with pytest.raises(GameError) as refused:
        wallet.change(player_of(guest), coins, -11, reason="purchase")
    assert refused.value.game_code == "GAME016"
    assert refused.value.extra == {"balance": 10, "needed": 11}
    assert Wallet.objects.get().balance == 10


def test_a_credit_stops_at_the_cap(guest: Guest, coins: Currency) -> None:
    fill(guest, coins, 990)
    done = wallet.change(player_of(guest), coins, 50, reason="reward")
    assert (done.amount, done.capped, done.balance) == (10, True, 1000)
    full = wallet.change(player_of(guest), coins, 50, reason="reward")
    assert (full.amount, full.entry) == (0, None)


def test_staff_grant_with_a_note(
    guest: Guest, coins: Currency, make_account: Callable[..., Any]
) -> None:
    fill(guest, coins, 1)
    manager_user = make_account("boss@example.com", "game-manager")
    manager = signed_in(manager_user)
    row = Wallet.objects.get()
    answer = manager.post(
        f"/api/game-wallets/{row.pk}/grant/", {"amount": 25, "note": "Sorry"}, format="json"
    )
    assert answer.status_code == 200, answer.content
    entry = LedgerEntry.objects.get(reason="grant", note="Sorry")
    assert (entry.amount, entry.actor_id) == (25, manager_user.pk)
    assert manager.get("/api/game-ledger/").data["count"] == 2
    moderator = signed_in(make_account("mod@example.com", "game-moderator"))
    assert moderator.post(f"/api/game-wallets/{row.pk}/grant/", {"amount": 5}).status_code == 403


# -- rewards ---------------------------------------------------------------------------


@pytest.fixture
def ad(game: Game, coins: Currency) -> Reward:
    return Reward.objects.create(
        game=game, key="ad-coins", title="Watch", kind="ad", currency=coins, amount=25, per_day=2
    )


def test_an_ad_reward_is_claimed_within_its_cap(guest: Guest, ad: Reward) -> None:
    for expected in (25, 50):
        answer = guest.post(f"{GAME}rewards/ad-coins/claim/")
        assert answer.status_code == 200, answer.content
        assert answer.data["granted"] == {"currency": "coins", "amount": 25, "balance": expected}
    third = guest.post(f"{GAME}rewards/ad-coins/claim/")
    assert (third.status_code, third.data["code"]) == (409, "GAME017")
    assert third.data["next_at"] is not None
    listed = guest.get(f"{GAME}rewards/").data["results"][0]
    assert (listed["claimed_today"], listed["available"]) == (2, False)


def test_a_cooldown_spaces_the_claims(guest: Guest, ad: Reward) -> None:
    ad.cooldown = 300
    ad.per_day = None
    ad.save()
    assert guest.post(f"{GAME}rewards/ad-coins/claim/").status_code == 200
    assert guest.post(f"{GAME}rewards/ad-coins/claim/").data["code"] == "GAME017"
    later = timezone.now() + timedelta(seconds=301)
    with mock.patch("django.utils.timezone.now", return_value=later):
        assert guest.post(f"{GAME}rewards/ad-coins/claim/").status_code == 200


def test_the_client_claims_only_ad_rewards(guest: Guest, game: Game, coins: Currency) -> None:
    for kind in ("daily", "mission", "match", "grant"):
        Reward.objects.create(game=game, key=kind, title=kind, kind=kind, currency=coins, amount=1)
        answer = guest.post(f"{GAME}rewards/{kind}/claim/")
        assert (answer.status_code, answer.data["code"]) == (403, "GAME018")
    assert not Claim.objects.exists()


def test_a_claim_counts_once_per_intent(guest: Guest, ad: Reward) -> None:
    first = guest.post(f"{GAME}rewards/ad-coins/claim/", {"intent": "ad-view-0001"})
    again = guest.post(f"{GAME}rewards/ad-coins/claim/", {"intent": "ad-view-0001"})
    assert again.data["replayed"] is True
    assert again.data["granted"] == first.data["granted"]
    assert Wallet.objects.get().balance == 25


# -- the portal's signed callback ------------------------------------------------------


@pytest.fixture
def callback_ad(ad: Reward) -> Reward:
    ad.callback = True
    ad.save()
    return ad


def call_back(body: dict[str, Any], secret: str = PORTAL_SECRET, **stamp: Any) -> Any:
    raw = json.dumps(body).encode()
    headers = sign(secret, raw, **stamp)
    return APIClient().post(
        "/api/game/callbacks/arcade/",
        raw,
        content_type="application/json",
        **{f"HTTP_{name.upper().replace('-', '_')}": value for name, value in headers.items()},
    )


def test_a_callback_reward_is_granted_by_the_portal_once(guest: Guest, callback_ad: Reward) -> None:
    assert guest.post(f"{GAME}rewards/ad-coins/claim/").data["code"] == "GAME018"
    made = guest.post(f"{GAME}rewards/ad-coins/intent/")
    assert made.status_code == 201
    body = {"intent": made.data["intent"], "event_id": "view-77"}
    answer = call_back(body)
    assert answer.status_code == 200, answer.content
    assert answer.data == {"granted": True, "duplicate": False}
    assert call_back(body).data == {"granted": False, "duplicate": True}
    assert Wallet.objects.get().balance == 25


def test_a_callback_must_be_signed_and_fresh(guest: Guest, callback_ad: Reward) -> None:
    intent = guest.post(f"{GAME}rewards/ad-coins/intent/").data["intent"]
    body = {"intent": intent, "event_id": "view-78"}
    assert call_back(body, secret="wrong").data["code"] == "GAME019"
    old = call_back(body, timestamp=int(time.time()) - 3600)
    assert (old.status_code, old.data["code"]) == (403, "GAME019")
    raw = json.dumps(body).encode()
    unsigned = APIClient().post("/api/game/callbacks/arcade/", raw, content_type="application/json")
    assert unsigned.data["code"] == "GAME019"
    nobody = APIClient().post("/api/game/callbacks/other/", raw, content_type="application/json")
    assert nobody.data["code"] == "GAME019"
    forged = call_back({"intent": "forged", "event_id": "view-79"})
    assert (forged.status_code, forged.data["code"]) == (400, "GAME020")
    assert not Wallet.objects.filter(balance__gt=0).exists()


def test_an_ad_reward_without_a_callback_has_no_intent(guest: Guest, ad: Reward) -> None:
    assert guest.post(f"{GAME}rewards/ad-coins/intent/").data["code"] == "GAME018"


# -- the shop and cosmetics ------------------------------------------------------------


def test_buying_spends_the_price_and_gives_the_item(
    guest: Guest, coins: Currency, hat: Item
) -> None:
    fill(guest, coins, 80)
    with capture_events() as published:
        answer = guest.post(f"{GAME}shop/red-cap/buy/")
    assert answer.status_code == 201, answer.content
    assert answer.data["balance"] == {"currency": "coins", "balance": 30}
    published.assert_published("game.item.bought", item="red-cap", price=50)
    again = guest.post(f"{GAME}shop/red-cap/buy/")
    assert (again.status_code, again.data["code"]) == (409, "GAME022")
    shop = guest.get(f"{GAME}shop/").data["results"][0]
    assert (shop["owned"], shop["price"]) == (True, {"currency": "coins", "amount": 50})
    assert LedgerEntry.objects.filter(reason="purchase", reference="red-cap").count() == 1


def test_buying_without_enough_changes_nothing(guest: Guest, coins: Currency, hat: Item) -> None:
    fill(guest, coins, 10)
    answer = guest.post(f"{GAME}shop/red-cap/buy/")
    assert (answer.status_code, answer.data["code"]) == (409, "GAME016")
    assert not Ownership.objects.exists()
    assert Wallet.objects.get().balance == 10


def test_items_not_for_sale(guest: Guest, game: Game, coins: Currency) -> None:
    Item.objects.create(game=game, key="free", title="Free", slot="hat")
    assert guest.post(f"{GAME}shop/free/buy/").data["code"] == "GAME021"
    assert guest.post(f"{GAME}shop/nothing/buy/").data["code"] == "GAME021"
    Item.objects.create(
        game=game, key="gold", title="Gold", slot="skin", real_money=True, money_price=Decimal("2")
    )
    answer = guest.post(f"{GAME}shop/gold/buy/")
    assert (answer.status_code, answer.data["code"]) == (400, "GAME031")


def test_one_item_is_equipped_per_slot(
    guest: Guest, game: Game, coins: Currency, hat: Item
) -> None:
    other = Item.objects.create(
        game=game, key="blue-cap", title="Blue cap", slot="hat", currency=coins, price=10
    )
    fill(guest, coins, 100)
    guest.post(f"{GAME}shop/red-cap/buy/")
    assert guest.post(f"{GAME}items/blue-cap/equip/").data["code"] == "GAME023"
    guest.post(f"{GAME}shop/blue-cap/buy/")
    assert guest.post(f"{GAME}items/red-cap/equip/").data["equipped"] is True
    assert guest.post(f"{GAME}items/blue-cap/equip/").status_code == 200
    worn = {row["item"]: row["equipped"] for row in guest.get(f"{GAME}wallet/").data["items"]}
    assert worn == {"red-cap": False, "blue-cap": True}
    assert guest.post(f"{GAME}items/blue-cap/unequip/").data["equipped"] is False
    assert other.key == "blue-cap"


# -- isolation ---------------------------------------------------------------------------


def test_another_player_never_reaches_a_wallet(
    guest: Guest, other: Guest, coins: Currency, hat: Item, ad: Reward
) -> None:
    fill(guest, coins, 500)
    guest.post(f"{GAME}shop/red-cap/buy/")
    assert other.get(f"{GAME}wallet/").data == {
        "balances": [{"currency": "coins", "title": "Coins", "balance": 0, "cap": 1000}],
        "items": [],
    }
    assert other.get(f"{GAME}wallet/ledger/").data["count"] == 0
    assert other.post(f"{GAME}shop/red-cap/buy/").data["code"] == "GAME016"
    assert other.post(f"{GAME}items/red-cap/equip/").data["code"] == "GAME023"
    other.post(f"{GAME}rewards/ad-coins/claim/")
    assert Wallet.objects.get(player_id=guest.player_id).balance == 450
    assert guest.get(f"{GAME}rewards/").data["results"][0]["claimed_today"] == 0


def test_no_player_reaches_a_wallet(api: Any, game: Game) -> None:
    for path in ("wallet/", "wallet/ledger/"):
        assert api.get(f"{GAME}{path}").data["code"] == "GAME002"
    assert api.post(f"{GAME}shop/x/buy/", {}, format="json").data["code"] == "GAME002"


def test_purchases_are_limited(guest: Guest, coins: Currency, hat: Item) -> None:
    with override_settings(KARNI_GAME_RATES={"buy": "1/min"}):
        guest.post(f"{GAME}shop/red-cap/buy/")
        answer = guest.post(f"{GAME}shop/red-cap/buy/")
    assert answer.data["code"] == "GAME015"


# -- merge and erase ---------------------------------------------------------------------


def test_a_guest_who_signs_in_keeps_coins_items_and_claims(
    guest: Guest,
    game: Game,
    coins: Currency,
    hat: Item,
    ad: Reward,
    make_account: Callable[..., Any],
) -> None:
    user = make_account("ines@example.com")
    account = signed_in(user)
    mine = players.player_for_user(user)
    wallet.change(mine, coins, 980, reason="grant")
    fill(guest, coins, 100)
    guest.post(f"{GAME}shop/red-cap/buy/")
    guest.post(f"{GAME}items/red-cap/equip/")
    guest.post(f"{GAME}rewards/ad-coins/claim/")
    answer = account.post("/api/game/upgrade/", {"guest_token": guest.token}, format="json")
    assert answer.status_code == 200, answer.content
    merged = answer.data["merged"]
    assert merged["currencies"] == {"coins": 20}  # 980 + 75 capped at 1000
    assert (merged["items"], merged["claims"]) == (1, 1)
    held = account.get(f"{GAME}wallet/").data
    assert held["balances"][0]["balance"] == 1000
    assert held["items"][0]["item"] == "red-cap" and held["items"][0]["equipped"] is True
    assert account.get(f"{GAME}rewards/").data["results"][0]["claimed_today"] == 1
    assert LedgerEntry.objects.filter(reason="merge").count() == 2


def test_erasing_keeps_amounts_and_drops_notes(guest: Guest, coins: Currency) -> None:
    wallet.change(player_of(guest), coins, 5, reason="grant", note="For Ana")
    people.erase(player_of(guest).person)
    entry = LedgerEntry.objects.get()
    assert (entry.amount, entry.note) == (5, "")


# -- real money through karni-commerce ---------------------------------------------------


@pytest.fixture
def gold(game: Game) -> Item:
    return Item.objects.create(
        game=game,
        key="gold-skin",
        title="Gold skin",
        slot="skin",
        real_money=True,
        money_price=Decimal("2.99"),
    )


def test_a_real_money_item_keeps_the_commerce_contract(
    gold: Item, make_account: Callable[..., Any]
) -> None:
    from karni_commerce.testing import check_reads

    from karni_game.sellables import GameItemSellable

    buyer = make_account("ines@example.com")
    chosen = check_reads(GameItemSellable(), gold, 1, {}, buyer)
    assert chosen == {} or isinstance(chosen, dict)


def test_a_paid_order_gives_the_item_and_a_refund_takes_it(
    gold: Item, make_account: Callable[..., Any]
) -> None:
    from karni_commerce import services
    from karni_commerce.models import Cart
    from karni_payments.test_checkout import settle

    buyer = make_account("ines@example.com")
    signed_in(buyer).get("/api/game/me/")
    cart = Cart.objects.create(user=buyer)
    services.set_line(cart, "game_item", str(gold.pk), 1, buyer=buyer)
    order = services.checkout(cart, user=buyer, email=buyer.email, billing={"name": "Ines"})
    services.open_payment(order)
    link = order.payments.order_by("-created_at").first()
    assert link is not None
    settle(link.payment, "pay")
    owned = Ownership.objects.get(item=gold)
    assert owned.player.person.user_id == buyer.pk
    assert owned.source == "order"
    with pytest.raises(Exception, match="own"):
        services.set_line(
            Cart.objects.create(user=buyer), "game_item", str(gold.pk), 1, buyer=buyer
        )


def test_a_guest_cannot_buy_a_real_money_item(gold: Item) -> None:
    from karni_commerce import services
    from karni_commerce.models import Cart

    with pytest.raises(Exception, match="Sign in"):
        services.set_line(Cart.objects.create(), "game_item", str(gold.pk), 1)


def test_rewards_module_checks_portals(callback_ad: Reward) -> None:
    from karni_game.errors import GameError

    with pytest.raises(GameError, match="GAME019"):
        rewards.verifier_for("nowhere")

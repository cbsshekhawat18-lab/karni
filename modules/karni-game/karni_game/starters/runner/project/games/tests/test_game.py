"""__GAME_TITLE__ on the server: a guest plays, the boards check every run, the shop and the
continue go through the server's rules, and one player never reaches another's saves,
scores or wallet."""

from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from karni.transfer.loading import load_content
from rest_framework.test import APIClient

GAME = "/api/game/__GAME_SLUG__/"


def _run(score: int, *, seconds: float = 30.0, seed: int | str = 7) -> dict[str, Any]:
    """A run as the game sends it (toRunRecord of @karni/game/sim)."""
    ticks = int(seconds * 120)
    return {
        "seed": str(seed),
        "inputs": [[0, '{"jump":false,"revive":false}'], [40, '{"jump":true,"revive":false}']],
        "duration_ms": round(ticks / 120 * 1000),
        "meta": {"karni_sim": 1, "dt": 1 / 120, "ticks": ticks, "hash": "0" * 16, "score": score},
    }


def _player() -> APIClient:
    client = APIClient()
    guest = client.post("/api/game/guest/", {}, format="json")
    assert guest.status_code == 201
    client.credentials(HTTP_X_PLAYER_TOKEN=guest.data["token"])
    return client


@pytest.fixture(autouse=True)
def _content(db: Any) -> None:
    load_content(Path(settings.BASE_DIR) / "content" / "game.yaml")


def test_a_guest_runs_and_the_run_counts_on_the_distance_board() -> None:
    player = _player()
    assert player.get(GAME).data["game"]["slug"] == "__GAME_SLUG__"
    sent = player.post(
        f"{GAME}boards/distance/scores/", {"value": 240, "run": _run(240)}, format="json"
    )
    assert sent.status_code == 201, sent.data
    assert sent.data["score"]["status"] == "accepted"
    board = player.get(f"{GAME}boards/distance/").data
    assert board["entries"][0]["value"] == 240 and board["entries"][0]["me"] is True


def test_every_score_needs_its_run_and_the_run_must_stand_behind_it() -> None:
    player = _player()
    bare = player.post(f"{GAME}boards/distance/scores/", {"value": 240}, format="json")
    assert bare.status_code == 400 and bare.data["code"] == "GAME014"
    # A run that says it reached 240 does not carry a score of 900.
    lie = player.post(
        f"{GAME}boards/distance/scores/", {"value": 900, "run": _run(240)}, format="json"
    )
    assert lie.status_code == 400 and lie.data["code"] == "GAME014"
    # Ten seconds of running cannot make 5000 points: held for staff, never on the board.
    fast = player.post(
        f"{GAME}boards/distance/scores/",
        {"value": 5000, "run": _run(5000, seconds=10)},
        format="json",
    )
    assert fast.status_code == 201 and fast.data["score"]["status"] == "flagged"
    assert player.get(f"{GAME}boards/distance/").data["entries"] == []


def test_todays_board_takes_only_a_run_on_the_servers_seed_of_the_day() -> None:
    player = _player()
    today = player.get(f"{GAME}daily/").data
    other = player.post(
        f"{GAME}boards/daily/scores/",
        {"value": 120, "run": _run(120, seed=int(today["seed"]) + 1)},
        format="json",
    )
    assert other.status_code == 400 and other.data["code"] == "GAME014"
    ok = player.post(
        f"{GAME}boards/daily/scores/",
        {"value": 120, "run": _run(120, seed=today["seed"])},
        format="json",
    )
    assert ok.status_code == 201 and ok.data["score"]["status"] == "accepted"


def test_coins_come_from_the_servers_rewards_and_buy_a_hat_at_the_servers_price() -> None:
    player = _player()
    assert player.post(f"{GAME}shop/cap/buy/", {}, format="json").status_code == 409  # no coins yet
    assert player.post(f"{GAME}daily/check-in/", {}, format="json").status_code == 200  # 20
    done = player.post(
        f"{GAME}progress/", {"events": [{"counter": "runs", "amount": 1}]}, format="json"
    )
    assert [row["key"] for row in done.data["unlocked"]] == ["first-run"]  # 30 more
    bought = player.post(f"{GAME}shop/cap/buy/", {}, format="json")
    assert bought.status_code in (200, 201), bought.data
    assert bought.data["balance"]["balance"] == 10
    worn = player.post(f"{GAME}items/cap/equip/", {}, format="json")
    assert worn.status_code == 200 and worn.data["equipped"] is True


def test_a_continue_is_granted_three_times_a_day_and_then_refused() -> None:
    player = _player()
    for _ in range(3):
        claimed = player.post(f"{GAME}rewards/continue/claim/", {}, format="json")
        assert claimed.status_code in (200, 201), claimed.data
    refused = player.post(f"{GAME}rewards/continue/claim/", {}, format="json")
    assert refused.status_code == 409 and refused.data["code"] == "GAME017"
    # A continue is worth no coins.
    coins = player.get(f"{GAME}wallet/").data["balances"]
    assert all(balance["balance"] == 0 for balance in coins)


def test_one_player_never_reads_or_changes_another_players_saves_scores_or_wallet() -> None:
    first, second = _player(), _player()
    save = {"data": {"best": 900, "runs": 4, "coins": 30}, "schema_version": 1, "base_version": 0}
    assert first.put(f"{GAME}saves/progress/", save, format="json").status_code == 200
    first.post(f"{GAME}daily/check-in/", {}, format="json")
    first.post(f"{GAME}progress/", {"events": [{"counter": "runs", "amount": 1}]}, format="json")
    first.post(f"{GAME}shop/cap/buy/", {}, format="json")
    first.post(f"{GAME}boards/distance/scores/", {"value": 300, "run": _run(300)}, format="json")

    # Saves: the second player's slot is its own, empty, and writing it leaves the first's alone.
    assert second.get(f"{GAME}saves/progress/").status_code == 404
    mine = {"data": {"best": 1, "runs": 1, "coins": 0}, "schema_version": 1, "base_version": 0}
    assert second.put(f"{GAME}saves/progress/", mine, format="json").status_code == 200
    assert first.get(f"{GAME}saves/progress/").data["data"]["best"] == 900
    # Wallet: nothing of the first player's coins or items.
    wallet = second.get(f"{GAME}wallet/").data
    assert all(balance["balance"] == 0 for balance in wallet["balances"]) and wallet["items"] == []
    assert second.post(f"{GAME}items/cap/equip/", {}, format="json").status_code >= 400
    # Scores: the first player's score is on the board under the first player only.
    board = second.get(f"{GAME}boards/distance/").data
    assert [(entry["value"], entry["me"]) for entry in board["entries"]] == [(300, False)]
    assert board["me"] is None
    assert second.get(f"{GAME}boards/distance/me/").data.get("best") in (None, {}, [])

"""Tile Match inside the app: a member plays as their account, and nobody else's game is theirs."""

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from karni.transfer.loading import load_content
from rest_framework.test import APIClient

GAME = "/api/game/tile-match/"


def member(email: str, *, verified: bool = True) -> APIClient:
    """A signed-in member: the app's own account is the game's player."""
    user = get_user_model().objects.create_user(
        email=email, password="a-long-test-password-1", email_verified=verified
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture(autouse=True)
def game(db: None) -> None:
    load_content(Path(settings.BASE_DIR) / "content" / "game.yaml")


def test_a_member_plays_as_their_account() -> None:
    alice = member("alice@example.test")
    run = {"seed": "7", "inputs": [[1, "0,5"], [2, "3,9"]]}
    score = alice.post(f"{GAME}boards/best/scores/", {"value": 950, "run": run}, format="json")
    assert score.status_code == 201
    assert alice.get("/api/game/me/").data["guest"] is False
    events = [{"counter": "deals_cleared", "amount": 1}]
    done = alice.post(f"{GAME}progress/", {"events": events}, format="json")
    assert [row["key"] for row in done.data["unlocked"]] == ["first-clear"]
    board = APIClient().get(f"{GAME}boards/best/").data
    assert [row["value"] for row in board["entries"]] == [950]


def test_todays_deal_takes_only_runs_on_the_days_seed() -> None:
    alice = member("alice@example.test")
    seed = alice.get(f"{GAME}daily/").data["seed"]
    daily = f"{GAME}boards/daily/scores/"
    good = {"value": 900, "run": {"seed": str(seed), "inputs": [[1, "0,1"]]}}
    assert alice.post(daily, good, format="json").status_code == 201
    other = {"value": 990, "run": {"seed": str(seed + 1), "inputs": [[1, "0,1"]]}}
    refused = alice.post(daily, other, format="json")
    assert refused.status_code == 400 and refused.data["code"] == "GAME014"


def test_an_account_plays_once_its_email_is_verified() -> None:
    bob = member("bob@example.test", verified=False)
    assert bob.get(f"{GAME}wallet/").data["code"] == "GAME004"


def test_one_member_never_reads_or_changes_anothers_game() -> None:
    alice, bob = member("alice@example.test"), member("bob@example.test")
    save = {"data": {"cleared": 3}, "schema_version": 1, "base_version": 0}
    assert alice.put(f"{GAME}saves/main/", save, format="json").status_code == 200
    assert bob.get(f"{GAME}saves/main/").status_code == 404
    mine = {"data": {"cleared": 99}, "schema_version": 1, "base_version": 0}
    assert bob.put(f"{GAME}saves/main/", mine, format="json").status_code == 200
    assert alice.get(f"{GAME}saves/main/").data["data"] == {"cleared": 3}
    for staff in ("/api/game-saves/", "/api/game-scores/", "/api/game-players/"):
        assert bob.get(staff).status_code == 403, staff


def test_staff_see_the_players_in_the_admin(admin_client: object) -> None:
    alice = member("alice@example.test")
    alice.get("/api/game/me/")
    page = admin_client.get(f"/{settings.KARNI_ADMIN_PATH}karni_game/player/")  # type: ignore[attr-defined]
    assert page.status_code == 200
    assert b"alice@example.test" in page.content

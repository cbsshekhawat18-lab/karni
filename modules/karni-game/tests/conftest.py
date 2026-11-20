"""Shared fixtures for the karni-game suite: games, guests, accounts and clients."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from django.core.cache import cache
from karni.accounts.roles import sync_roles
from karni.celery import create_celery_app
from karni.testing import user_with_roles
from rest_framework.test import APIClient

from karni_game import hooks
from karni_game.models import Game

celery_app = create_celery_app("karni-game-tests")

TOKEN_HEADER = "HTTP_X_PLAYER_TOKEN"


@pytest.fixture(autouse=True)
def _setup(db: None) -> Iterator[None]:
    sync_roles()
    cache.clear()
    yield
    cache.clear()
    hooks.clear()


@pytest.fixture
def game() -> Game:
    return Game.objects.create(slug="block-hopper", title="Block Hopper")


@pytest.fixture
def api() -> APIClient:
    return APIClient()


class Guest:
    """A guest: its token and a client that sends it."""

    def __init__(self, token: str, player_id: str) -> None:
        self.token = token
        self.player_id = player_id
        self.client = APIClient()
        self.client.credentials(**{TOKEN_HEADER: token})

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(path, params)

    def post(self, path: str, data: Any = None) -> Any:
        return self.client.post(path, data or {}, format="json")

    def put(self, path: str, data: Any) -> Any:
        return self.client.put(path, data, format="json")

    def patch(self, path: str, data: Any) -> Any:
        return self.client.patch(path, data, format="json")

    def delete(self, path: str) -> Any:
        return self.client.delete(path)


@pytest.fixture
def make_guest() -> Callable[..., Guest]:
    def make(handle: str = "") -> Guest:
        answer = APIClient().post("/api/game/guest/", {"handle": handle}, format="json")
        assert answer.status_code == 201, answer.content
        return Guest(answer.data["token"], str(answer.data["player"]["id"]))

    return make


@pytest.fixture
def guest(make_guest: Callable[..., Guest]) -> Guest:
    return make_guest("Swift Fox")


@pytest.fixture
def other(make_guest: Callable[..., Guest]) -> Guest:
    return make_guest("Quiet Owl")


@pytest.fixture
def make_account() -> Callable[..., Any]:
    def make(email: str = "ana@example.com", *roles: str, verified: bool = True) -> Any:
        return user_with_roles(*(roles or ("customer",)), email=email, email_verified=verified)

    return make


def signed_in(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client

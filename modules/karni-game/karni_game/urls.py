"""The game API's routes (docs/game-api.md). A project mounts them with one line::

    path("api/game/", include("karni_game.urls")),

before ``path("api/", include("karni.api.urls"))``. ``karni check`` reports
``GAME030`` while the line is missing.

Override / escape hatch: mount your own subclasses of the views of
:mod:`karni_game.api` on these paths instead of the include.
"""

from __future__ import annotations

from django.urls import path

from karni_game import api

app_name = "karni_game"

urlpatterns = [
    path("guest/", api.GuestView.as_view(), name="guest"),
    path("me/", api.MeView.as_view(), name="me"),
    path("upgrade/", api.UpgradeView.as_view(), name="upgrade"),
    path("<slug:game>/", api.GameDetailView.as_view(), name="game"),
    path("<slug:game>/saves/", api.SavesView.as_view(), name="saves"),
    path("<slug:game>/saves/<str:slot>/", api.SaveView.as_view(), name="save"),
    path("<slug:game>/boards/<slug:board>/", api.BoardView.as_view(), name="board"),
    path("<slug:game>/boards/<slug:board>/me/", api.BoardMeView.as_view(), name="board-me"),
    path("<slug:game>/boards/<slug:board>/scores/", api.ScoresView.as_view(), name="scores"),
]

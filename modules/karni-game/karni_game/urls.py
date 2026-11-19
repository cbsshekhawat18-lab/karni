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
    path("callbacks/<slug:portal>/", api.CallbackView.as_view(), name="callback"),
    path("<slug:game>/", api.GameDetailView.as_view(), name="game"),
    path("<slug:game>/saves/", api.SavesView.as_view(), name="saves"),
    path("<slug:game>/saves/<str:slot>/", api.SaveView.as_view(), name="save"),
    path("<slug:game>/boards/<slug:board>/", api.BoardView.as_view(), name="board"),
    path("<slug:game>/boards/<slug:board>/me/", api.BoardMeView.as_view(), name="board-me"),
    path("<slug:game>/boards/<slug:board>/scores/", api.ScoresView.as_view(), name="scores"),
    path("<slug:game>/wallet/", api.WalletView.as_view(), name="wallet"),
    path("<slug:game>/wallet/ledger/", api.LedgerView.as_view(), name="ledger"),
    path("<slug:game>/rewards/", api.RewardsView.as_view(), name="rewards"),
    path("<slug:game>/rewards/<slug:reward>/claim/", api.ClaimView.as_view(), name="claim"),
    path("<slug:game>/rewards/<slug:reward>/intent/", api.IntentView.as_view(), name="intent"),
    path("<slug:game>/shop/", api.ShopView.as_view(), name="shop"),
    path("<slug:game>/shop/<slug:item>/buy/", api.BuyView.as_view(), name="buy"),
    path("<slug:game>/items/<slug:item>/equip/", api.EquipView.as_view(), name="equip"),
    path("<slug:game>/items/<slug:item>/unequip/", api.UnequipView.as_view(), name="unequip"),
    path("<slug:game>/daily/", api.DailyView.as_view(), name="daily"),
    path("<slug:game>/daily/check-in/", api.CheckInView.as_view(), name="check-in"),
    path("<slug:game>/progress/", api.ProgressView.as_view(), name="progress"),
    path("<slug:game>/achievements/", api.AchievementsView.as_view(), name="achievements"),
    path("<slug:game>/missions/", api.MissionsView.as_view(), name="missions"),
]

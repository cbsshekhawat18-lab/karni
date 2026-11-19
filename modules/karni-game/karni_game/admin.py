"""The admin of the games: explicit registrations where staff act, derived ones elsewhere.

* **Players**, with their person (name and email) and the actions *Ban from the
  boards*, *Unban* and *Revoke the guest token*.
* **Scores**, filtered by status, with each run shown read only, and the
  actions *Accept* and *Reject* for flagged runs.
* **Wallets**, read only, with their ledger, and the action *Grant currency*
  (an amount and a note, a ledger entry per wallet).
* **Ledger entries**, read only: every change of a balance.

The games, their boards, currencies, rewards, items, achievements, missions
and config values are the derived admin (``AdminMeta``): boards, currencies
and config values show inline on their game. A person's erase and merge are
the people admin's, and they reach the players (:mod:`karni_game.people`).

Override / escape hatch: ``admin.site.unregister(Model)`` and register your
own subclass of these.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.utils import timezone
from karni.admin import KarniInlineMixin, KarniModelAdmin

from karni_game import players, scores, wallet
from karni_game.errors import GameError
from karni_game.models import LedgerEntry, Player, Score, Wallet

__all__ = ["LedgerEntryAdmin", "PlayerAdmin", "ScoreAdmin", "WalletAdmin"]


@admin.register(Player)
class PlayerAdmin(KarniModelAdmin):
    """The players with their person; ban, unban and revoke a guest's token."""

    list_display: ClassVar[list[str]] = [
        "handle",
        "person_name",
        "person_email",
        "guest",
        "last_seen_at",
        "banned_at",
    ]
    search_fields: ClassVar[list[str]] = ["handle", "person__display_name", "person__email"]
    list_select_related: ClassVar[list[str]] = ["person"]
    readonly_fields: ClassVar[list[str]] = ["person", "last_seen_at", "banned_at"]
    actions: ClassVar[list[str]] = ["ban", "unban", "revoke_token"]

    @admin.display(description="Person")
    def person_name(self, obj: Player) -> str:
        return str(obj.person)

    @admin.display(description="Email")
    def person_email(self, obj: Player) -> str:
        return obj.person.email

    @admin.display(description="Guest", boolean=True)
    def guest(self, obj: Player) -> bool:
        return obj.is_guest

    @admin.action(description="Ban from the boards")
    def ban(self, request: HttpRequest, queryset: QuerySet[Player]) -> None:
        count = queryset.filter(banned_at__isnull=True).update(banned_at=timezone.now())
        self.message_user(request, f"{count} player(s) banned from the boards.")

    @admin.action(description="Unban")
    def unban(self, request: HttpRequest, queryset: QuerySet[Player]) -> None:
        count = queryset.update(banned_at=None, ban_reason="")
        self.message_user(request, f"{count} player(s) unbanned.")

    @admin.action(description="Revoke the guest token")
    def revoke_token(self, request: HttpRequest, queryset: QuerySet[Player]) -> None:
        for player in queryset:
            players.revoke_token(player)
        self.message_user(request, f"{queryset.count()} token(s) revoked.")


@admin.register(Score)
class ScoreAdmin(KarniModelAdmin):
    """Every score, its run read only; accept or reject the flagged ones."""

    list_display: ClassVar[list[str]] = ["value", "board", "player", "status", "source", "day"]
    list_filter: ClassVar[list[str]] = ["status", "board__game", "board"]
    search_fields: ClassVar[list[str]] = ["player__handle"]
    list_select_related: ClassVar[list[str]] = ["board", "player"]
    readonly_fields: ClassVar[list[str]] = [
        "board",
        "player",
        "value",
        "status",
        "day",
        "run",
        "source",
        "reviewed_at",
    ]
    actions: ClassVar[list[str]] = ["accept", "reject"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.action(description="Accept: the score counts")
    def accept(self, request: HttpRequest, queryset: QuerySet[Score]) -> None:
        for score in queryset.exclude(status="accepted"):
            scores.accept(score)
        self.message_user(request, "The selected scores count on their boards.")

    @admin.action(description="Reject: take the score off the boards")
    def reject(self, request: HttpRequest, queryset: QuerySet[Score]) -> None:
        for score in queryset.exclude(status="rejected"):
            scores.reject(score, "Rejected in the admin.")
        self.message_user(request, "The selected scores are off the boards.")


class LedgerInline(KarniInlineMixin, admin.TabularInline):
    model = LedgerEntry
    extra = 0
    can_delete = False
    fields = ("created_at", "amount", "balance_after", "reason", "reference", "note")
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Wallet)
class WalletAdmin(KarniModelAdmin):
    """The balances, read only, with their ledger; grant currency with a note."""

    list_display: ClassVar[list[str]] = ["player", "currency", "balance", "updated_at"]
    list_filter: ClassVar[list[str]] = ["currency__game", "currency"]
    search_fields: ClassVar[list[str]] = ["player__handle"]
    readonly_fields: ClassVar[list[str]] = ["player", "currency", "balance"]
    inlines: ClassVar[list[Any]] = [LedgerInline]
    actions: ClassVar[list[str]] = ["grant_currency"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.action(description="Grant currency")
    def grant_currency(
        self, request: HttpRequest, queryset: QuerySet[Wallet]
    ) -> HttpResponse | None:
        if request.POST.get("apply"):
            try:
                amount = int(str(request.POST.get("amount", "")))
            except ValueError:
                self.message_user(request, "The amount is a whole number.", messages.ERROR)
                return None
            note = str(request.POST.get("note", ""))[:200]
            done = 0
            for row in queryset.select_related("player", "currency"):
                try:
                    wallet.change(
                        row.player,
                        row.currency,
                        amount,
                        reason="grant",
                        actor=request.user,
                        note=note,
                    )
                    done += 1
                except GameError as exc:
                    self.message_user(request, f"{row}: {exc.message}", messages.ERROR)
            self.message_user(request, f"{done} wallet(s) changed by {amount}.")
            return None
        return TemplateResponse(
            request,
            "karni_game/admin/grant.html",
            {
                **self.admin_site.each_context(request),
                "title": "Grant currency",
                "wallets": list(queryset.select_related("player", "currency")),
                "opts": self.model._meta,
            },
        )


@admin.register(LedgerEntry)
class LedgerEntryAdmin(KarniModelAdmin):
    """Every change of a balance, read only."""

    list_display: ClassVar[list[str]] = [
        "wallet",
        "amount",
        "balance_after",
        "reason",
        "created_at",
    ]
    list_filter: ClassVar[list[str]] = ["reason"]
    search_fields: ClassVar[list[str]] = ["wallet__player__handle", "reference"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

"""The CRM's reactions to its own records (imported at startup by karni.events)."""

from karni import preferences, timeline
from karni.events import on_transition

from crm.models import Deal


@on_transition(Deal, "stage", to="won")
def record_a_won_deal(deal: Deal) -> None:
    _record(deal, "won", f"Deal won: {deal.title}")


@on_transition(Deal, "stage", to="lost")
def record_a_lost_deal(deal: Deal) -> None:
    _record(deal, "lost", f"Deal lost: {deal.title}")


def _record(deal: Deal, moment: str, title: str) -> None:
    """Write the deal's timeline entry, while the connection crm.deal_timeline is on."""
    if not preferences.active("crm.deal_timeline"):
        return
    timeline.record(
        kind=f"crm.deal.{moment}",
        title=title,
        body=deal.lost_reason or "",
        subjects=[deal, deal.company],
        data={"value": str(deal.value), "stage": moment},
    )

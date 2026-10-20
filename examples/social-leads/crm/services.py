"""What a lead goes through: status changes, assignment, conversion, scoring.

Every change writes a LeadActivity so the timeline is the audit trail the
screens show. The scorer is the one piece of the original that called an
external AI; here it is a pure function with the same contract (0-100 plus a
one-line reason) so the endpoint, the screen and the tests keep working.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils import timezone

from crm.models import Lead, LeadActivity


def record(
    lead: Lead, actor: Any, activity_type: str, content: str, **metadata: Any
) -> LeadActivity:
    return LeadActivity.objects.create(
        lead=lead, actor=actor, activity_type=activity_type, content=content, metadata=metadata
    )


def assign(lead: Lead, actor: Any, user: Any | None) -> Lead:
    previous = lead.assigned_to_id
    lead.assigned_to = user
    lead.save(update_fields=["assigned_to", "updated_at"])
    who = user.email if user is not None else "(unassigned)"
    record(
        lead,
        actor,
        "assignment",
        f"Assigned to {who}",
        previous_user_id=str(previous) if previous else None,
        new_user_id=str(lead.assigned_to_id) if lead.assigned_to_id else None,
    )
    return lead


def set_status(lead: Lead, actor: Any, status: str, notes: str = "") -> Lead:
    previous = lead.status
    lead.status = status
    if notes:
        lead.notes = f"{lead.notes}\n\n{notes}" if lead.notes else notes
    lead.save(update_fields=["status", "notes", "updated_at"])
    record(
        lead,
        actor,
        "status_change",
        f"Status: {previous} → {status}" + (f" — {notes}" if notes else ""),
        previous=previous,
        new=status,
    )
    return lead


def convert(lead: Lead, actor: Any, value: Decimal) -> Lead:
    lead.status = Lead.Status.CONVERTED
    lead.conversion_value = value
    lead.converted_at = timezone.now()
    lead.save(update_fields=["status", "conversion_value", "converted_at", "updated_at"])
    record(lead, actor, "status_change", f"Converted (₹{value:,.0f})", conversion_value=str(value))
    return lead


def score(lead: Lead) -> tuple[int, str]:
    """0-100 and why: budget, a clear ask, reachable contact details, no spam signals."""
    points, reasons = 20, []
    if lead.budget:
        points += 30
        reasons.append("budget stated")
    if lead.interest:
        points += 25
        reasons.append("clear interest")
    if lead.email:
        points += 10
        reasons.append("reachable by email")
    if lead.location:
        points += 5
    if lead.status == Lead.Status.SPAM:
        points, reasons = 0, ["marked as spam"]
    points = max(0, min(100, points))
    return points, ", ".join(reasons) or "no budget, interest or contact details yet"


def apply_score(lead: Lead, actor: Any) -> Lead:
    points, reason = score(lead)
    lead.quality_score, lead.quality_reason = points, reason
    lead.save(update_fields=["quality_score", "quality_reason", "updated_at"])
    record(lead, actor, "note", f"Scored {points}/100: {reason}", score=points, reason=reason)
    return lead

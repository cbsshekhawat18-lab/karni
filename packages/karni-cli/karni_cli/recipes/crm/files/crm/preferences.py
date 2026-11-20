"""The CRM part's settings: Settings, CRM (karni.preferences)."""

from karni import preferences
from pydantic import Field


@preferences.section("crm", title="CRM", change="role:crm-manager")
class CrmPreferences(preferences.Section):
    """When an open deal needs attention."""

    stale_after_days: int = Field(
        30,
        ge=1,
        le=365,
        description=(
            "An open deal nobody changed for this many days is listed as stale "
            "(GET /api/deals/stale/)."
        ),
    )

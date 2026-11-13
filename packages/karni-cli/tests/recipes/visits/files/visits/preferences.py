"""The visits test part's settings section (karni.preferences)."""

from karni import preferences
from pydantic import Field


@preferences.section("visits", title="Visits")
class VisitPreferences(preferences.Section):
    """How a visit is greeted."""

    greeting: str = Field(
        "Welcome back", max_length=60, description="Said at the door."
    )

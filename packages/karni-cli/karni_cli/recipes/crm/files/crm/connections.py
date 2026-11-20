"""What the CRM part does when other things are installed (karni.preferences)."""

from karni import preferences

preferences.connection(
    "crm.deal_timeline",
    needs=["timeline"],
    default=True,
    describe="A won or lost deal is written on the deal's timeline.",
)

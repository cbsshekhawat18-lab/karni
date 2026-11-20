"""What the shop does when other things are installed (karni.preferences)."""

from karni import preferences

preferences.connection(
    "shop.parcel_timeline",
    needs=["timeline"],
    default=True,
    describe="A parcel sent or delivered is written on its order's timeline.",
)

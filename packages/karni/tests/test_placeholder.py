"""karni.placeholder (experimental): drawn, deterministic placeholder images."""

from __future__ import annotations

import io

from PIL import Image

from karni.placeholder import initials, placeholder_image
from karni.seeding import placeholder_image as from_seeding


def test_the_same_label_and_key_draw_the_same_picture() -> None:
    first = placeholder_image("Brass Desk Lamp", key="Lighting")
    again = placeholder_image("Brass Desk Lamp", key="Lighting")
    assert first.read() == again.read()
    assert first.name == "brass-desk-lamp.png"


def test_another_label_draws_another_picture_in_the_key_colours() -> None:
    lamp = Image.open(io.BytesIO(placeholder_image("Brass Desk Lamp", key="Lighting").read()))
    candle = Image.open(io.BytesIO(placeholder_image("Beeswax Candles", key="Lighting").read()))
    board = Image.open(io.BytesIO(placeholder_image("Beeswax Candles", key="Kitchen").read()))
    assert lamp.tobytes() != candle.tobytes()
    assert lamp.getpixel((2, 2)) == candle.getpixel((2, 2))  # one background per key
    assert candle.getpixel((2, 2)) != board.getpixel((2, 2))


def test_it_is_a_png_of_the_size_asked_for() -> None:
    image = Image.open(io.BytesIO(placeholder_image("Tote", size=(320, 200), name="x.png").read()))
    assert (image.format, image.size) == ("PNG", (320, 200))


def test_initials() -> None:
    assert initials("Brass Desk Lamp") == "BD"
    assert initials("  ") == "?"
    assert initials("A5 Dot-Grid notebook") == "AD"


def test_the_seeding_module_offers_it() -> None:
    assert from_seeding is placeholder_image

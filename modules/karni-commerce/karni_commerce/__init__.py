"""karni-commerce (experimental): one cart, checkout and order path for anything a project sells.

A project's apps sell different things (a product, a booking, a course, a
listing) through the same path: a cart line names a *kind* and an item,
checkout turns the cart into an :class:`~karni_commerce.models.Order` with
its lines copied, karni-payments takes the money, and the settlement and
refunds move the order. Each kind is a :class:`~karni_commerce.sellables.Sellable`
adapter the selling app registers in its ``<app>/sellables.py``: commerce
calls the adapter and never imports the app.

Project code talks to :mod:`karni_commerce.services`.
"""

from __future__ import annotations

from importlib import metadata as _metadata

#: The version of the commerce contract (the sellable adapter, the order path and the
#: signals of :mod:`karni_commerce.events`). Experimental until six recipes use it.
CONTRACT = 1

try:
    __version__ = _metadata.version("karni-commerce")  # [project] version in pyproject.toml
except _metadata.PackageNotFoundError:  # a source tree on sys.path, never installed
    __version__ = "0+unknown"

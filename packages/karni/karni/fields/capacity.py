"""``CapacityField``: a remaining-quantity counter the database keeps at or above zero.

"N of this exists, do not oversell it" (seats, stock, licences) fails in
production when code reads the remaining count, checks it, then writes the
new value: two requests read the same last seat. ``CapacityField`` makes the
database the referee::

    class TicketTier(BaseModel):
        quantity = models.PositiveIntegerField()
        remaining = CapacityField(total="quantity")

* The column carries ``CHECK ("remaining" >= 0)`` and, with a ``total``, the
  table carries ``CHECK ("remaining" <= "quantity")`` (a constraint named
  ``<table>_remaining_lte_quantity``, created by the model's migration), so
  no write from anywhere can oversell or invent capacity.
* :func:`karni.capacity.reserve` / :func:`~karni.capacity.release` are the
  one way to consume it: a locked, conditional ``UPDATE``.
* A new row starts full (``remaining = quantity``). Changing ``quantity``
  shifts ``remaining`` by the same amount in SQL (``remaining = remaining +
  20``), and ``save()`` never writes an absolute value, so a stale instance
  cannot overwrite reservations made since it was loaded. Lowering the total
  below what is already reserved is refused by the CHECK (``E985``).
* The field is ``editable=False``: read-only in the API and the admin.

Override / escape hatch: omit ``total`` for a counter without a ceiling
(stock that is replenished with ``release()``); pass ``default=`` for its
starting value. ``QuerySet.update()`` bypasses all of this except the CHECK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models

from karni.exceptions import KarniImproperlyConfigured

__all__ = ["CapacityField"]


class CapacityField(models.PositiveIntegerField):
    """What is left of a limited resource; changed only by ``reserve()`` / ``release()``.

    :param total: name of the field holding the full quantity on the same
        model (an integer field). New rows start at it; changing it shifts the
        remaining count; the CHECK keeps the remaining count at or below it.
    """

    description = "A remaining quantity the database never lets drop below zero"

    def __init__(self, *args: Any, total: str | None = None, **kwargs: Any) -> None:
        if total is not None and (not isinstance(total, str) or not total.isidentifier()):
            raise KarniImproperlyConfigured(
                f"CapacityField(total={total!r}): total names the integer field holding the "
                "full quantity, e.g. CapacityField(total='quantity').",
                code="E986",
            )
        self.total = total
        kwargs.setdefault("editable", False)
        if total is not None:
            kwargs.setdefault("blank", True)  # filled from the total on insert
        super().__init__(*args, **kwargs)

    if TYPE_CHECKING:  # the instance attribute holds the count, not the field

        def __get__(self, instance: Any, owner: Any) -> Any: ...
        def __set__(self, instance: Any, value: Any) -> None: ...

    def deconstruct(self) -> Any:
        name, _path, args, kwargs = super().deconstruct()
        if kwargs.get("editable") is False:
            kwargs.pop("editable")
        if self.total is not None:
            kwargs["total"] = self.total
            if kwargs.get("blank") is True:
                kwargs.pop("blank")
        return name, "karni.fields.CapacityField", args, kwargs

    def total_field(self) -> models.Field[Any, Any] | None:
        if self.total is None:
            return None
        field: models.Field[Any, Any] = self.model._meta.get_field(self.total)
        return field

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        """Insert: the value (the total when unset). Update: ``F(column) + <total change>``.

        An ``UPDATE`` never writes an absolute remaining count, so a stale
        instance cannot undo reservations made since it was loaded.
        """
        if add:
            value = getattr(model_instance, self.attname)
            if value is None and self.total is not None:
                value = getattr(model_instance, self.total_field().attname)  # type: ignore[union-attr]
                setattr(model_instance, self.attname, value)
            return value
        from karni.guards import capacity_shift

        return models.F(self.attname) + capacity_shift(model_instance, self)

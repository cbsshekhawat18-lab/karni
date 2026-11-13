"""What happens in the shop, as signals any app of the project can receive.

Receive one in ``<app>/listeners.py`` (Karni imports it at startup)::

    from django.dispatch import receiver
    from shop.events import shipment_shipped


    @receiver(shipment_shipped)
    def tell_the_courier(sender, shipment, **kwargs):
        ...

The orders themselves are karni-commerce's: ``karni_commerce.events`` sends
``order_placed``, ``order_paid``, ``order_cancelled`` and ``order_refunded``.
A payment or a refund that changes is ``karni_payments.events``.

Each signal is sent inside the transaction that made the change: a receiver that
raises undoes it. For work that waits for the commit (an email, a call to another
system), use ``transaction.on_commit`` in the receiver. :data:`EVENTS` names each
signal as the family events do (``shop.shipment.shipped``).
"""

from django.dispatch import Signal

#: An order's parcel left: ``shipment`` (its order, carrier and tracking number).
shipment_shipped = Signal()

#: An order's parcel arrived: ``shipment``.
shipment_delivered = Signal()

#: A product's stock that no order holds fell to the low-stock level or below after an
#: order took it: ``product``, and ``variation`` when it is one of its variations.
product_low_stock = Signal()

#: The family event name of each signal.
EVENTS = {
    "shop.shipment.shipped": shipment_shipped,
    "shop.shipment.delivered": shipment_delivered,
    "shop.product.low_stock": product_low_stock,
}

"""What happens in the shop, as signals any app of the project can receive.

Receive one in ``<app>/listeners.py`` (Karni imports it at startup)::

    from django.dispatch import receiver
    from shop.events import order_placed


    @receiver(order_placed)
    def welcome_first_order(sender, order, **kwargs):
        ...

Besides these:

* an order's status moves (paid, shipped, delivered, failed, cancelled,
  refunded) are Karni's own lifecycle events:
  ``@on_transition(Order, "status", to="shipped")`` from ``karni.events``, or
  ``karni.lifecycle.state_changed``;
* a payment or a refund that changes is ``karni_payments.events``;
* a row created, changed or deleted (an address, a product) is
  ``on_created``, ``on_updated`` and ``on_deleted`` of ``karni.events``.

Each signal is sent inside the transaction that made the change: a receiver
that raises undoes it. For work that should wait for the commit (an email, a
call to another system), use ``transaction.on_commit`` in the receiver.
"""

from django.dispatch import Signal

#: A customer or a guest placed an order (it waits for its payment): ``order``.
order_placed = Signal()

#: Stock moved for an order: ``product``, ``quantity``, ``order`` and ``reason``:
#: ``reserved`` (checkout holds it), ``released`` (the order did not get paid),
#: ``taken`` (the order is paid) or ``returned`` (a paid order was cancelled or refunded).
stock_changed = Signal()

#: A product's stock fell to its low-stock level or below after an order took it: ``product``.
stock_low = Signal()

#: A visitor's cart joined the cart of the customer who signed in: ``cart``, ``user``.
cart_merged = Signal()

#: A customer who signed in got the orders they placed as a guest with their email:
#: ``user``, ``orders``.
customer_orders_claimed = Signal()

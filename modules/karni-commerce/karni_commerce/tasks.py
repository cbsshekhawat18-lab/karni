"""Commerce's Celery tasks.

``karni_commerce.tasks.release_expired`` cancels the orders whose payment did
not come in time, so their items are free again. Checkout also runs it, so a
project without a beat schedule still frees them at the next checkout.
Schedule it every few minutes (docs/scheduling.md)::

    CELERY_BEAT_SCHEDULE = {
        "commerce-release-expired": {
            "task": "karni_commerce.tasks.release_expired",
            "schedule": 300,
        },
    }
"""

from __future__ import annotations

from celery import shared_task

from karni_commerce import services


@shared_task(name="karni_commerce.tasks.release_expired")
def release_expired() -> int:
    """Cancel the pending orders past their hold. Returns how many."""
    return services.release_expired()

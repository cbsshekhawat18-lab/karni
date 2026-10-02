"""Maintenance Celery tasks for :mod:`karni.accounts` (contract amendment A8).

``karni.conf`` schedules :func:`flush_expired_tokens` daily under the
``CELERY_BEAT_SCHEDULE`` key ``"karni-flush-expired-tokens"``.

Override / escape hatch: projects may remove or replace that schedule key in
their ``settings.py`` after calling ``karni_settings()``, point the schedule
at their own task, or call the task (it is a plain function) from any cron
runner instead of beat.
"""

from __future__ import annotations

from celery import shared_task

__all__ = ["flush_expired_tokens"]


@shared_task(name="karni.accounts.tasks.flush_expired_tokens")
def flush_expired_tokens() -> dict[str, int | bool]:
    """Purge expired auth tokens.

    Runs SimpleJWT's ``flushexpiredtokens`` management command (dropping
    expired blacklisted/outstanding refresh tokens) when
    ``rest_framework_simplejwt.token_blacklist`` is installed — it is
    unconditionally in Karni's defaults (amendment A3), the guard only covers
    projects that removed it — and deletes expired
    :class:`~karni.accounts.models.OneTimeToken` rows (verify-email /
    reset-password / change-email secrets past their TTL).

    Returns a small summary dict so django-celery-results shows what happened.
    """
    from django.apps import apps
    from django.core.management import call_command
    from django.utils import timezone

    from karni.accounts.models import OneTimeToken

    blacklist_flushed = False
    if apps.is_installed("rest_framework_simplejwt.token_blacklist"):
        call_command("flushexpiredtokens")
        blacklist_flushed = True

    deleted, _per_model = (
        OneTimeToken.objects.all_with_deleted().filter(expires_at__lt=timezone.now()).hard_delete()
    )
    return {"jwt_blacklist_flushed": blacklist_flushed, "one_time_tokens_deleted": deleted}

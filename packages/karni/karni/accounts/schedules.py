"""Hourly: delete expired sign-in codes, declared only while ``KARNI_EMAIL_OTP`` is on."""

from __future__ import annotations

from django.conf import settings

from karni.schedule import every

if getattr(settings, "KARNI_EMAIL_OTP", False):
    every(hours=1, task="karni.accounts.tasks.flush_login_codes", name="karni-flush-login-codes")

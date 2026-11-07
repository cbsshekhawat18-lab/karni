"""The project passes Django's system checks, which include every Karni check."""

from django.core.management import call_command


def test_system_checks_are_clean():
    call_command(
        "check", fail_level="ERROR"
    )  # W501 and W580 flag the test cache, which is per process

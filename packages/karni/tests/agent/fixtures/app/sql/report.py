# mypy: ignore-errors
# Raw SQL is allowed under */sql/* (K104 allowance): zero findings.
from django.db import connection


def run() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")

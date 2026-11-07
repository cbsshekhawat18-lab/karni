"""Models over tables another system owns, a SQL view, and a second database.

On the default database:

* ``Region`` and ``Sale``: read-only external tables of a reporting system.
  ``Sale`` lives in the PostgreSQL schema ``reporting``
  (``db_table = 'reporting"."sales'``) when the suite runs on PostgreSQL, and
  in a plain table on SQLite, which has no schemas.
* ``Target``: an external table the API and the admin may write
  (``writable = True``), with change history.
* ``RegionTotal``: a SQL view of the sales per region. The pytest plugin
  gives it a table; ``tests/test_external.py`` replaces that with the view.

On the ``second`` database:

* ``Stock``: a read-only external table of a warehouse system.
* ``ProductMapping``: a table Karni manages there (it migrates only on
  ``second``), composed of UUIDModel and TimestampedModel: AuditedModel's
  user columns would point at another database.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from karni.models import TimestampedModel, UUIDModel

#: The suite runs on PostgreSQL (the CI overlay), so the schema-qualified table is real.
POSTGRES: bool = str(settings.DATABASES["default"]["ENGINE"]).endswith("postgresql")


class Region(models.Model):
    code = models.CharField(primary_key=True, max_length=10)
    name = models.CharField(max_length=60)

    class Meta:
        managed = False
        db_table = "ext_region"
        ordering = ["code"]

    class Karni:
        external = True

    def __str__(self) -> str:
        return self.name


class Sale(models.Model):
    id = models.IntegerField(primary_key=True)
    region = models.ForeignKey(
        Region, on_delete=models.DO_NOTHING, db_constraint=False, db_column="region_code"
    )
    product = models.CharField(max_length=80)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    sold_on = models.DateField()

    class Meta:
        managed = False
        db_table = 'reporting"."sales' if POSTGRES else "reporting_sales"
        ordering = ["id"]

    class Karni:
        external = True
        scope_paths = {"region": "region"}
        field_roles = {"amount": ["staff"]}

    def __str__(self) -> str:
        return self.product


class Target(models.Model):
    id = models.AutoField(primary_key=True)
    region = models.CharField(max_length=10)
    year = models.IntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        managed = False
        db_table = "ext_target"
        ordering = ["id"]

    class Karni:
        external = True
        writable = True
        audit = True

    def __str__(self) -> str:
        return f"{self.region} {self.year}"


class RegionTotal(models.Model):
    region = models.CharField(primary_key=True, max_length=10)
    total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        managed = False
        db_table = "ext_region_total"
        ordering = ["region"]

    class Karni:
        external = True

    def __str__(self) -> str:
        return self.region


class Stock(models.Model):
    sku = models.CharField(primary_key=True, max_length=20)
    quantity = models.IntegerField()

    class Meta:
        managed = False
        db_table = "wh_stock"
        ordering = ["sku"]

    class Karni:
        external = True
        database = "second"

    def __str__(self) -> str:
        return self.sku


class ProductMapping(UUIDModel, TimestampedModel):
    sku = models.CharField(max_length=20, unique=True)
    label = models.CharField(max_length=80)

    class Meta:
        ordering = ["sku"]

    class Karni:
        database = "second"

    def __str__(self) -> str:
        return self.label

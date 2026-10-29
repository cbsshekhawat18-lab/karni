"""External tables, SQL views and a second database (karni.db, experimental).

The models live in :mod:`tests.externalapp`. Every test that touches the
``second`` database asks for it (``databases=["default", "second"]``), so
the rest of the suite never creates it.
"""

from __future__ import annotations

import datetime as dt
import warnings
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, connections, models, router
from django.db.models import Q
from django.test import Client, override_settings
from django.test.utils import isolate_apps
from django.urls import reverse

from karni.accounts.permissions import assign_role
from karni.accounts.roles import register_scope, sync_roles
from karni.db import (
    DatabaseRouter,
    database_for,
    external_models,
    is_external,
    is_read_only,
    routed_aliases,
    split_table,
)
from karni.db import checks as db_checks
from karni.db.introspection import inspect_table, relation_exists, relation_kind
from karni.exceptions import KarniAssertionError
from karni.models import BaseModel
from karni.testing import assert_crud, client_as, user_with_roles
from karni.testing.api import CrudReport
from tests.externalapp import viewsets
from tests.externalapp.models import (
    POSTGRES,
    ProductMapping,
    Region,
    RegionTotal,
    Sale,
    Stock,
    Target,
)

BOTH = ["default", "second"]

ROUTES = override_settings(
    ROOT_URLCONF="tests.externalapp.urls",
    KARNI_API_ROUTER="tests.externalapp.urls.get_router",
)


@pytest.fixture
def routes() -> Iterator[None]:
    with ROUTES:
        yield


def _region(code: str = "north", name: str = "North") -> Region:
    return Region.objects.create(code=code, name=name)


def _sale(pk: int, region: Region, amount: str = "10.00", product: str = "Lamp") -> Sale:
    return Sale.objects.create(
        id=pk, region=region, product=product, amount=Decimal(amount), sold_on=dt.date(2026, 3, 1)
    )


def _tables(alias: str) -> set[str]:
    connection = connections[alias]
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor, include_views=True))


# the declarations


def test_the_declarations_are_read_from_class_karni() -> None:
    assert is_external(Sale) and is_read_only(Sale)
    assert is_external(Target) and not is_read_only(Target)
    assert not is_external(ProductMapping) and not is_read_only(ProductMapping)
    assert database_for(Stock) == "second" and database_for(ProductMapping) == "second"
    assert database_for(Sale) is None
    assert routed_aliases() == frozenset({"second"})
    assert set(external_models()) >= {Region, Sale, Target, RegionTotal, Stock}
    assert ProductMapping not in external_models()


def test_split_table_reads_the_schema_quoting_trick() -> None:
    assert split_table('reporting"."sales') == ("reporting", "sales")
    assert split_table("sales") == (None, "sales")


def test_a_many_to_many_table_follows_the_model_that_declares_it() -> None:
    with isolate_apps("tests.externalapp"):

        class Shelf(models.Model):
            tags = models.ManyToManyField("Label")

            class Meta:
                app_label = "externalapp"

            class Karni:
                database = "second"

        class Label(models.Model):
            class Meta:
                app_label = "externalapp"

            class Karni:
                database = "second"

        through = Shelf.tags.through
        assert database_for(through) == "second"


# routing


def test_reads_and_writes_go_to_the_declared_alias() -> None:
    assert router.db_for_read(Stock) == "second"
    assert router.db_for_write(ProductMapping) == "second"
    assert router.db_for_read(Sale) == DEFAULT_DB_ALIAS
    assert router.db_for_write(get_user_model()) == DEFAULT_DB_ALIAS


def test_migrations_run_only_on_the_models_own_alias() -> None:
    karni = DatabaseRouter()
    assert karni.allow_migrate("second", "externalapp", "productmapping") is True
    assert karni.allow_migrate("default", "externalapp", "productmapping") is False
    for name in ("stock", "sale", "region", "target"):  # external: never
        assert karni.allow_migrate("default", "externalapp", name) is False
        assert karni.allow_migrate("second", "externalapp", name) is False
    assert karni.allow_migrate("default", "testapp", "event") is None
    assert karni.allow_migrate("second", "testapp", "event") is False
    # RunPython / RunSQL without hints: nothing runs on a routed alias.
    assert karni.allow_migrate("second", "karni_accounts") is False
    assert karni.allow_migrate("default", "karni_accounts") is None
    assert karni.allow_migrate("second", "externalapp", model_name="productmapping") is True
    # An alias no model names is left to Django (and the project's routers).
    assert karni.allow_migrate("replica", "testapp", "event") is None


def test_relations_across_aliases_are_refused() -> None:
    karni = DatabaseRouter()
    mapping = ProductMapping(sku="A-1", label="Lamp")
    user = get_user_model()(email="someone@example.com")
    assert karni.allow_relation(mapping, user) is False
    assert router.allow_relation(mapping, user) is False
    assert karni.allow_relation(mapping, ProductMapping(sku="B-2", label="Desk")) is True
    assert karni.allow_relation(Sale(id=1), Region(code="north")) is None


def test_karni_settings_lists_the_router_after_the_projects_own(make_settings: Any) -> None:
    assert make_settings()["DATABASE_ROUTERS"] == ["karni.db.DatabaseRouter"]
    own = make_settings(preset={"DATABASE_ROUTERS": ["myproject.routers.ReplicaRouter"]})
    assert own["DATABASE_ROUTERS"] == ["myproject.routers.ReplicaRouter", "karni.db.DatabaseRouter"]


@pytest.mark.django_db(databases=BOTH)
def test_the_second_database_holds_only_the_models_routed_there() -> None:
    second, default = _tables("second"), _tables("default")
    assert "externalapp_productmapping" in second
    assert "externalapp_productmapping" not in default
    assert "karni_accounts_user" in default and "karni_accounts_user" not in second
    assert "auth_permission" not in second and "django_content_type" not in second
    # The external table of the second database comes from the pytest plugin, there only.
    assert "wh_stock" in second and "wh_stock" not in default


@pytest.mark.django_db(databases=BOTH)
def test_rows_of_a_routed_model_are_written_to_its_database() -> None:
    ProductMapping.objects.create(sku="A-1", label="Lamp")
    Stock.objects.create(sku="A-1", quantity=4)
    assert ProductMapping.objects.using("second").count() == 1
    assert Stock.objects.using("second").get(sku="A-1").quantity == 4
    with connections["second"].cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM externalapp_productmapping")
        assert cursor.fetchone()[0] == 1


# the pytest plugin


def test_the_plugin_created_the_external_tables_of_the_default_database(db: None) -> None:
    tables = _tables("default")
    assert {"ext_region", "ext_target", "ext_region_total"} <= tables
    assert relation_exists(connections["default"], Sale._meta.db_table)
    assert relation_exists(connections["default"], Region._meta.db_table)
    assert not relation_exists(connections["default"], Stock._meta.db_table)


@pytest.mark.skipif(not POSTGRES, reason="schemas are PostgreSQL's")
def test_the_plugin_created_the_schema_of_a_schema_qualified_table(db: None) -> None:
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema = 'reporting' AND table_name = 'sales'"
        )
        assert cursor.fetchone() == ("BASE TABLE",)


def test_the_plugin_option_turns_table_creation_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.db.models.signals import post_migrate

    from karni.testing import pytest_plugin
    from karni.testing.external import after_migrate

    connected: list[Any] = []
    monkeypatch.setattr(post_migrate, "connect", lambda *a, **k: connected.append((a, k)))
    for value, expected in (("off", 0), ("create", 1)):
        config = SimpleNamespace(getoption=lambda *a, value=value, **k: value, getini=lambda n: "")
        pytest_plugin._external_tables(config)  # type: ignore[arg-type]
        assert len(connected) == expected
    assert connected[0][0][0] is after_migrate
    bad = SimpleNamespace(getoption=lambda *a, **k: None, getini=lambda n: "sometimes")
    with pytest.raises(pytest.UsageError, match="karni_external_tables"):
        pytest_plugin._external_tables(bad)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_create_external_tables_creates_only_what_is_missing() -> None:
    from karni.testing.external import create_external_tables

    assert create_external_tables() == []  # the plugin did it already
    with connections["default"].schema_editor() as editor:
        editor.delete_model(Region)
    try:
        assert create_external_tables(models=[Region, Target]) == ["ext_region"]
    finally:
        assert relation_exists(connections["default"], "ext_region")


def test_a_schema_on_sqlite_is_skipped_with_a_warning(db: None) -> None:
    if POSTGRES:
        pytest.skip("SQLite only")
    from karni.testing.external import create_external_tables

    with isolate_apps("tests.externalapp"):

        class Ledger(models.Model):
            class Meta:
                app_label = "externalapp"
                managed = False
                db_table = 'finance"."ledger'

            class Karni:
                external = True

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert create_external_tables(models=[Ledger]) == []
    assert any("no schema 'finance'" in str(item.message) for item in caught)


# read-only through the API


@pytest.mark.django_db
def test_assert_crud_picks_the_read_only_variant_for_an_external_model(routes: None) -> None:
    report = assert_crud(viewsets.SaleViewSet, "analyst")
    assert isinstance(report, CrudReport)
    assert {"list", "retrieve", "create", "update", "delete", "schema"} <= set(report.passed)
    assert not report.warnings  # refused writes are the point, not a gap


@pytest.mark.django_db
def test_every_write_answers_405_and_writes_nothing(routes: None) -> None:
    sale = _sale(1, _region())
    client = client_as("analyst")
    detail = f"/api/sales/{sale.pk}/"
    for method, url in (
        ("post", "/api/sales/"),
        ("put", detail),
        ("patch", detail),
        ("delete", detail),
    ):
        response = getattr(client, method)(url, {"product": "Desk"}, format="json")
        assert response.status_code == 405, (method, response.content)
        assert "read-only" in response.json()["detail"]
    assert client_as(None).post("/api/sales/", {}, format="json").status_code == 405
    assert Sale.objects.get().product == "Lamp" and Sale.objects.count() == 1
    listed = client.get("/api/sales/")
    assert listed.status_code == 200 and listed.json()["count"] == 1
    assert "POST" not in listed["Allow"] and "GET" in listed["Allow"]
    assert "DELETE" not in client.options(detail)["Allow"]
    assert client.get("/api/sales/import/").status_code == 405
    assert client.get("/api/sales/export/?format=csv").status_code == 200


@pytest.mark.django_db
def test_the_schema_documents_no_write_of_a_read_only_model(routes: None) -> None:
    from karni.testing.schema import find_operation, generate_schema

    document = generate_schema(cached=False)
    assert find_operation(document, "/api/sales/", "GET") is not None
    assert find_operation(document, "/api/sales/1/", "GET") is not None
    for method, path in (
        ("POST", "/api/sales/"),
        ("PUT", "/api/sales/1/"),
        ("PATCH", "/api/sales/1/"),
        ("DELETE", "/api/sales/1/"),
        ("POST", "/api/sales/import/"),
    ):
        assert find_operation(document, path, method) is None, (method, path)
    assert find_operation(document, "/api/targets/", "POST") is not None


@pytest.mark.django_db
def test_assert_crud_fails_a_read_only_model_that_accepts_writes(routes: None) -> None:
    with pytest.raises(KarniAssertionError) as caught:
        user = user_with_roles("analyst", "staff")  # staff sees amount, so a write can succeed
        assert_crud(viewsets.LeakySaleViewSet, "analyst", user=user, skip=("schema",))
    assert "answered 201, expected 405" in str(caught.value)


@pytest.mark.django_db
def test_read_only_false_checks_writes_and_fails_on_the_405s(routes: None) -> None:
    with pytest.raises(KarniAssertionError, match="answered 405"):
        assert_crud(viewsets.SaleViewSet, "analyst", read_only=False, skip=("schema",))


@pytest.mark.django_db
def test_a_writable_external_model_takes_writes_and_keeps_history(routes: None) -> None:
    from karni.audit.models import ChangeLog

    report = assert_crud(viewsets.TargetViewSet, "analyst")
    assert {"create", "update", "delete"} <= set(report.passed)
    client = client_as("analyst")
    created = client.post(
        "/api/targets/", {"region": "north", "year": 2026, "amount": "120.00"}, format="json"
    )
    assert created.status_code == 201, created.content
    target = Target.objects.get(pk=created.json()["id"])
    assert ChangeLog.objects.for_object(target).filter(action="create").exists()


def test_change_history_stays_off_for_a_read_only_external_model() -> None:
    from karni.audit.services import audited

    with isolate_apps("tests.externalapp"):

        class Snapshot(models.Model):
            class Meta:
                app_label = "externalapp"
                managed = False

            class Karni:
                external = True
                audit = True

        assert not audited(Snapshot)
    assert audited(Target)


# access, grants and row scope


@pytest.mark.django_db
def test_field_roles_hide_a_column_of_an_external_model(routes: None) -> None:
    _sale(1, _region())
    analyst = client_as("analyst")
    assert "amount" not in analyst.get("/api/sales/").json()["results"][0]
    staff = client_as("analyst", "staff")
    assert staff.get("/api/sales/").json()["results"][0]["amount"] == "10.00"


@pytest.mark.django_db
def test_role_grants_and_row_scope_apply_to_an_external_model(routes: None) -> None:
    roles = {
        "staff": {"system": True, "grants": {"*": "all"}},
        "regional": {"grants": {"externalapp.sale:view": "related:region"}},
    }
    north, south = _region(), _region("south", "South")
    _sale(1, north)
    _sale(2, south)
    with override_settings(KARNI_ROLES=roles):
        sync_roles()
        user = user_with_roles("regional")
        user.region = north  # related:region compares Sale.region with user.region
        response = client_as(user=user).get("/api/granted-sales/")
        assert response.status_code == 200, response.content
        assert [row["id"] for row in response.json()["results"]] == [1]
        assert client_as(user=user).get("/api/granted-sales/2/").status_code == 404
        assert client_as(user=user).post("/api/granted-sales/", {}).status_code == 405
        outsider = client_as()
        assert outsider.get("/api/granted-sales/").status_code == 403


@pytest.mark.django_db
def test_permission_keys_exist_for_external_models() -> None:
    from karni.accounts.roles import permission_keys

    keys = permission_keys()
    assert keys["externalapp.sale:view"] is Sale
    assert keys["externalapp.stock:view"] is Stock


# the admin


def _superuser() -> Client:
    user = get_user_model().objects.create_superuser(
        email="admin@example.com", password="a-strong-password-123"
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_the_admin_shows_a_read_only_external_model_read_only(routes: None) -> None:
    _sale(7, _region(), product="Floor lamp")
    client = _superuser()
    changelist = reverse("admin:externalapp_sale_changelist")
    response = client.get(changelist)
    assert response.status_code == 200 and b"Floor lamp" in response.content
    assert reverse("admin:externalapp_sale_add").encode() not in response.content
    assert client.get(reverse("admin:externalapp_sale_add")).status_code == 403
    change = reverse("admin:externalapp_sale_change", args=[7])
    page = client.get(change)
    assert page.status_code == 200
    assert page.context["has_change_permission"] is False
    assert b'name="_save"' not in page.content
    assert client.post(change, {"product": "Desk"}).status_code == 403
    assert client.get(reverse("admin:externalapp_sale_delete", args=[7])).status_code == 403
    assert Sale.objects.get().product == "Floor lamp"
    model_admin = __import__("django.contrib.admin", fromlist=["site"]).site._registry[Sale]
    request = SimpleNamespace(user=get_user_model().objects.get(), GET={}, META={})
    assert "delete_selected" not in model_admin.get_actions(request)
    exported = client.get(reverse("admin:externalapp_sale_changelist"))
    assert exported.status_code == 200


@pytest.mark.django_db
def test_the_admin_edits_a_writable_external_model(routes: None) -> None:
    target = Target.objects.create(region="north", year=2026, amount=Decimal("5.00"))
    client = _superuser()
    change = reverse("admin:externalapp_target_change", args=[target.pk])
    response = client.post(change, {"region": "south", "year": 2027, "amount": "6.00"})
    assert response.status_code == 302, response.content
    target.refresh_from_db()
    assert (target.region, target.year) == ("south", 2027)


@pytest.mark.django_db
def test_the_admin_row_scope_applies_to_an_external_model(routes: None) -> None:
    from django.contrib.auth.models import Permission

    register_scope("north_only", lambda user, model: Q(region_id="north"))
    roles = {
        "staff": {"system": True, "grants": {"*": "all"}},
        "northern": {"grants": {"externalapp.sale:view": "custom:north_only"}},
    }
    _sale(1, _region(), product="North lamp")
    _sale(2, _region("south", "South"), product="South lamp")
    with override_settings(KARNI_ROLES=roles):
        sync_roles()
        user = get_user_model().objects.create_user(
            email="north@example.com", password="a-strong-password-123", is_staff=True
        )
        user.user_permissions.add(Permission.objects.get(codename="view_sale"))
        assign_role(user, "northern")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("admin:externalapp_sale_changelist"))
        assert response.status_code == 200
        assert b"North lamp" in response.content and b"South lamp" not in response.content


@pytest.mark.django_db(databases=BOTH)
def test_the_admin_edits_a_model_on_the_second_database(routes: None) -> None:
    client = _superuser()
    response = client.post(
        reverse("admin:externalapp_productmapping_add"), {"sku": "A-1", "label": "Lamp"}
    )
    assert response.status_code == 302, response.content
    assert ProductMapping.objects.using("second").get().label == "Lamp"
    stock = client.get(reverse("admin:externalapp_stock_changelist"))
    assert stock.status_code == 200


@pytest.mark.django_db(databases=BOTH)
def test_the_api_serves_both_kinds_of_model_on_the_second_database(routes: None) -> None:
    assert_crud(viewsets.ProductMappingViewSet, "analyst")
    Stock.objects.create(sku="A-1", quantity=3)
    client = client_as("analyst")
    assert client.get("/api/stock/").json()["results"] == [{"sku": "A-1", "quantity": 3}]
    assert client.post("/api/stock/", {"sku": "B-2", "quantity": 1}).status_code == 405


# schema-qualified tables (PostgreSQL)


@pytest.mark.django_db
def test_filters_ordering_select_related_and_export_on_the_sales_table(routes: None) -> None:
    north, south = _region(), _region("south", "South")
    _sale(1, north, "30.00", "Desk")
    _sale(2, south, "20.00", "Lamp")
    _sale(3, north, "10.00", "Chair")
    found = list(
        Sale.objects.select_related("region").filter(region__name="North").order_by("-amount")
    )
    assert [sale.product for sale in found] == ["Desk", "Chair"]
    assert found[0].region.name == "North"
    client = client_as("analyst", "staff")
    listed = client.get("/api/sales/", {"region": "north", "ordering": "-amount"}).json()
    assert [row["product"] for row in listed["results"]] == ["Desk", "Chair"]
    expanded = client.get("/api/sales/1/", {"expand": "region"}).json()
    assert expanded["region"]["name"] == "North"
    assert client.get("/api/sales/", {"search": "Lamp"}).json()["count"] == 1
    csv = client.get("/api/sales/export/?format=csv")
    assert csv.status_code == 200 and b"Desk" in b"".join(
        csv.streaming_content if csv.streaming else [csv.content]
    )
    admin_client = _superuser()
    page = admin_client.get(reverse("admin:externalapp_sale_changelist"), {"o": "-4"})
    assert page.status_code == 200 and b"Desk" in page.content


# a SQL view


def _make_view() -> None:
    sales = connections["default"].ops.quote_name(Sale._meta.db_table)
    with connections["default"].cursor() as cursor:
        cursor.execute("DROP TABLE ext_region_total")
        cursor.execute(
            "CREATE VIEW ext_region_total AS SELECT region_code AS region, "
            f"SUM(amount) AS total FROM {sales} GROUP BY region_code"
        )


@pytest.mark.django_db
def test_a_sql_view_is_read_like_a_table(routes: None) -> None:
    north, south = _region(), _region("south", "South")
    _sale(1, north, "30.00")
    _sale(2, north, "12.50")
    _sale(3, south, "20.00")
    _make_view()
    assert relation_kind(connections["default"], "ext_region_total") == "view"
    totals = {row.region: row.total for row in RegionTotal.objects.all()}
    assert totals == {"north": Decimal("42.50"), "south": Decimal("20.00")}
    response = client_as("analyst").get("/api/region-totals/")
    assert response.status_code == 200
    assert [row["region"] for row in response.json()["results"]] == ["north", "south"]
    assert client_as("analyst").post("/api/region-totals/", {}).status_code == 405
    assert db_checks.check_external_tables(["default"], models=[RegionTotal]) == []
    assert inspect_table(connections["default"], "ext_region_total")["kind"] == "view"


# seeding and the scaling check skip external models


@pytest.mark.django_db
def test_seeding_skips_external_models() -> None:
    from karni.seeding import seed, seed_plan

    plan = seed_plan()
    assert not any(is_external(model) for model in plan)
    assert ProductMapping in plan
    report = seed(models=[Sale, Region, Target], count=3)
    assert report.rows == {} and Sale.objects.count() == 0


@pytest.mark.django_db
def test_the_scaling_check_skips_external_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from karni.testing import _source
    from karni.testing.performance import scaling_cases

    monkeypatch.setattr(
        _source, "project_app_configs", lambda: [django_apps.get_app_config("externalapp")]
    )
    with ROUTES:
        cases = {case.id for case in scaling_cases()}
    assert cases == {"ProductMappingViewSet.list", "ProductMappingViewSet.retrieve"}


# the model-base rule


def test_model_base_accepts_external_models_and_only_with_managed_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from karni.testing import architecture

    real = [django_apps.get_app_config("externalapp")]
    monkeypatch.setattr(architecture, "project_app_configs", lambda: real)
    assert architecture.check_model_base() == []
    with isolate_apps("tests.externalapp"):

        class Half(models.Model):  # external without managed = False
            class Meta:
                app_label = "externalapp"

            class Karni:
                external = True

        cfg = SimpleNamespace(get_models=lambda: [Half], name="externalapp", label="externalapp")
        monkeypatch.setattr(architecture, "project_app_configs", lambda: [cfg])
        assert [v.message for v in architecture.check_model_base()] == [
            "Half inherits django.db.models.Model directly"
        ]


def test_the_single_file_check_accepts_an_external_class() -> None:
    from karni.agent.check import check_source

    accepted = (
        "from django.db import models\n\n\n"
        "class Sale(models.Model):\n"
        "    class Meta:\n        managed = False\n\n"
        "    class Karni:\n        external = True\n"
    )
    half = accepted.replace("managed = False", "ordering = ['id']")
    assert [f.rule_id for f in check_source("app/models.py", accepted)] == []
    assert [f.rule_id for f in check_source("app/models.py", half)] == ["model-base"]


# the checks


def _ids(messages: list[Any]) -> list[str]:
    return [message.id for message in messages]


def test_the_installed_models_pass_the_database_checks() -> None:
    assert db_checks.check_database_options() == []
    assert db_checks.check_database_router() == []


def test_option_checks_name_every_misuse() -> None:
    with isolate_apps("tests.externalapp"):

        class Managed(models.Model):  # external without managed = False
            class Meta:
                app_label = "externalapp"

            class Karni:
                external = True

        class Lost(models.Model):
            class Meta:
                app_label = "externalapp"
                managed = False

            class Karni:
                external = True
                database = "warehouse"

        class Typo(models.Model):
            class Meta:
                app_label = "externalapp"

            class Karni:
                external = "yes"
                database = ""

        class Pointless(models.Model):
            class Meta:
                app_label = "externalapp"

            class Karni:
                writable = True

        class Elsewhere(models.Model):
            class Meta:
                app_label = "externalapp"

            class Karni:
                database = "second"

        class Joined(models.Model):  # on default, pointing at a row on second
            other = models.ForeignKey(Elsewhere, on_delete=models.CASCADE)

            class Meta:
                app_label = "externalapp"

        class Audited(BaseModel):  # created_by / updated_by point at the user table
            class Meta(BaseModel.Meta):
                app_label = "externalapp"

            class Karni:
                database = "second"

        def run(*found: type[models.Model]) -> list[str]:
            config = SimpleNamespace(get_models=lambda: list(found))
            return _ids(db_checks.check_database_options([config]))

        assert run(Managed) == ["karni.E270"]
        assert run(Lost) == ["karni.E271"]
        assert run(Typo) == ["karni.E275", "karni.E275"]
        assert run(Pointless) == ["karni.W541"]
        assert run(Joined) == ["karni.E276"]
        assert run(Audited) == ["karni.E276", "karni.E276"]
        assert run(Elsewhere) == []


class ReplicaRouter:
    """A project's own router, unrelated to Karni's."""

    def db_for_read(self, model: Any, **hints: Any) -> None:
        return None


@override_settings(DATABASE_ROUTERS=["tests.test_external.ReplicaRouter"])
def test_a_missing_router_is_a_warning() -> None:
    assert _ids(db_checks.check_database_router()) == ["karni.W542"]


class OwnRouter(DatabaseRouter):
    """A project's subclass counts as Karni's router."""


@override_settings(DATABASE_ROUTERS=["tests.test_external.OwnRouter"])
def test_a_subclass_of_the_router_counts() -> None:
    assert db_checks.check_database_router() == []


@pytest.mark.django_db(databases=BOTH)
def test_every_external_model_matches_its_table() -> None:
    assert db_checks.check_external_tables() == []


@pytest.mark.django_db
def test_the_comparison_finds_a_missing_table_column_and_type() -> None:
    with isolate_apps("tests.externalapp"):

        class Ghost(models.Model):
            class Meta:
                app_label = "externalapp"
                managed = False
                db_table = "ext_ghost"

            class Karni:
                external = True

        class Wider(models.Model):
            code = models.CharField(primary_key=True, max_length=10)
            name = models.CharField(max_length=60)
            population = models.IntegerField()

            class Meta:
                app_label = "externalapp"
                managed = False
                db_table = "ext_region"

            class Karni:
                external = True

        class Mistyped(models.Model):
            code = models.CharField(primary_key=True, max_length=10)
            name = models.DateTimeField()

            class Meta:
                app_label = "externalapp"
                managed = False
                db_table = "ext_region"

            class Karni:
                external = True

        found = db_checks.check_external_tables(["default"], models=[Ghost, Wider, Mistyped])
    assert _ids(found) == ["karni.E272", "karni.E273", "karni.E274"]
    assert "'ext_ghost'" in found[0].msg
    assert "population" in found[1].msg and "columns: code, name" in found[1].msg
    assert "DateTimeField (datetime)" in found[2].msg and "holds text values" in found[2].msg
    with override_settings(SILENCED_SYSTEM_CHECKS=["karni.E273"]):
        assert db_checks.check_external_tables(["default"], models=[Wider]) == []


def test_a_database_that_does_not_answer_is_a_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from django.db.utils import ConnectionHandler

    gone = {"ENGINE": "django.db.backends.sqlite3", "NAME": str(tmp_path / "no" / "such.db")}
    handler = ConnectionHandler({"default": gone, "warehouse": gone})
    monkeypatch.setattr(db_checks, "connections", handler)
    with isolate_apps("tests.externalapp"):

        class Far(models.Model):
            class Meta:
                app_label = "externalapp"
                managed = False

            class Karni:
                external = True
                database = "warehouse"

        found = db_checks.check_external_tables(models=[Far])
    assert _ids(found) == ["karni.W540"]
    assert "'warehouse' did not answer" in found[0].msg and "Far" in found[0].msg
    errors, warnings_ = db_checks.external_check_failures(models=[Far])
    assert errors == [] and warnings_[0].startswith("karni.W540")


@pytest.mark.django_db(databases=BOTH)
def test_karni_check_runs_the_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    from io import StringIO

    from karni.exceptions import KarniCommandError

    monkeypatch.setattr(db_checks, "external_models", lambda: [Region])
    monkeypatch.setattr(
        "karni.management.commands.karni_check.entry_points", lambda **kw: []
    )  # the architecture hooks have their own tests
    out, err = StringIO(), StringIO()
    call_command("karni_check", stdout=out, stderr=err)
    assert "backend checks: ok" in out.getvalue()
    with connections["default"].cursor() as cursor:
        cursor.execute("DROP TABLE ext_region")
    with pytest.raises(KarniCommandError):
        call_command("karni_check", stdout=out, stderr=err)
    assert "external tables: externalapp.Region: karni.E272" in err.getvalue()
    deploy_err = StringIO()
    with pytest.raises(KarniCommandError):  # the development values fail it
        call_command("karni_check", "--deploy", stdout=StringIO(), stderr=deploy_err)
    assert "external tables" not in deploy_err.getvalue()


# the inspection behind karni make model --external


def _inspect(table: str, database: str = "default") -> dict[str, Any]:
    import json
    from io import StringIO

    from karni.management.commands.karni_inspect import MARKER

    out = StringIO()
    call_command("karni_inspect", table, "--database", database, stdout=out)
    line = out.getvalue().strip()
    assert line.startswith(MARKER)
    return dict(json.loads(line[len(MARKER) :]))


@pytest.mark.django_db
def test_karni_inspect_describes_a_table_with_inspectdb() -> None:
    found = _inspect("ext_target")
    assert found["status"] == "ok" and found["kind"] == "table"
    by_name = {field["name"]: field for field in found["fields"]}
    assert by_name["id"]["type"] == "AutoField" and by_name["id"]["params"] == {"primary_key": True}
    assert by_name["region"] == {
        "name": "region",
        "type": "CharField",
        "params": {"max_length": 10},
        "notes": [],
    }
    if POSTGRES:
        assert by_name["amount"]["params"] == {"max_digits": 12, "decimal_places": 2}
    else:  # SQLite keeps no precision, so inspectdb guesses and says so
        assert by_name["amount"]["params"] == {"max_digits": 10, "decimal_places": 5}
        assert "guessed" in by_name["amount"]["notes"][0]
    assert by_name["year"]["type"] == "IntegerField"


@pytest.mark.django_db
def test_karni_inspect_picks_a_key_for_a_view_and_notes_foreign_keys() -> None:
    _make_view()
    view = _inspect("ext_region_total")
    assert view["kind"] == "view"
    region = view["fields"][0]
    assert region["name"] == "region" and region["params"].get("primary_key") is True
    assert "no primary key" in view["notes"][0]
    with connections["default"].cursor() as cursor:
        cursor.execute(
            'CREATE TABLE ext_order (id integer PRIMARY KEY, "Customer" varchar(30) NULL, '
            "target_id integer NOT NULL REFERENCES ext_target (id))"
        )
    order = {field["name"]: field for field in _inspect("ext_order")["fields"]}
    assert order["customer"]["params"] == {
        "db_column": "Customer",
        "max_length": 30,
        "blank": True,
        "null": True,
    }
    assert "A foreign key to ext_target.id" in order["target_id"]["notes"][-1]


@pytest.mark.django_db(databases=BOTH)
def test_karni_inspect_says_what_is_wrong() -> None:
    assert _inspect("nowhere")["status"] == "missing"
    assert _inspect("ext_target", "warehouse")["status"] == "unknown-alias"
    assert _inspect("wh_stock", "second")["status"] == "ok"
    if POSTGRES:
        found = _inspect("reporting.sales")
        assert found["status"] == "ok" and found["db_table"] == 'reporting"."sales'
        assert [field["name"] for field in found["fields"]] == [
            "id",
            "region_code",
            "product",
            "amount",
            "sold_on",
        ]
    else:
        assert _inspect("reporting.sales")["status"] == "no-schemas"


def test_karni_inspect_reports_a_database_that_does_not_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from django.db.utils import ConnectionHandler

    from karni.management.commands import karni_inspect

    gone = {"ENGINE": "django.db.backends.sqlite3", "NAME": str(tmp_path / "no" / "such.db")}
    monkeypatch.setattr(karni_inspect, "connections", ConnectionHandler({"default": gone}))
    answer = karni_inspect.Command().describe("sales", "default")
    assert answer["status"] == "unreachable" and answer["error"]


def test_db_table_for_reads_schema_dot_table() -> None:
    from karni.management.commands.karni_inspect import db_table_for

    assert db_table_for("reporting.sales") == 'reporting"."sales'
    assert db_table_for('reporting"."sales') == 'reporting"."sales'
    assert db_table_for("sales") == "sales"


@pytest.mark.django_db
@pytest.mark.parametrize("table", ["ext_target", "ext_region", "reporting.sales"])
def test_a_generated_model_matches_its_table(table: str) -> None:
    """karni make model --external end to end: inspect, render, define, compare."""
    external = pytest.importorskip("karni_cli.generators.external")
    if table == "reporting.sales" and not POSTGRES:
        table = "reporting_sales"
    answer = _inspect(table)
    source = external.render(
        "Generated", answer, database="default", writable=False, order=None, line_length=99
    )
    with isolate_apps("tests.externalapp"):
        namespace: dict[str, Any] = {"models": models, "__name__": "tests.externalapp.models"}
        meta = "class Meta:\n        app_label = 'externalapp'"
        code = compile(source.replace("class Meta:", meta), "<generated>", "exec")
        exec(code, namespace)  # noqa: S102 - the source the generator just wrote
        generated = namespace["Generated"]
        assert is_read_only(generated) and generated._meta.db_table == answer["db_table"]
        assert db_checks.check_external_tables(["default"], models=[generated]) == []


@pytest.mark.django_db
def test_an_entered_key_is_sent_on_create_and_never_changes(routes: None) -> None:
    region = _region()
    client = client_as(user=user_with_roles("analyst", "staff"))
    body = {"id": 50, "region": region.pk, "product": "Desk", "amount": "9.00"}
    created = client.post("/api/leaky-sales/", {**body, "sold_on": "2026-03-01"}, format="json")
    assert created.status_code == 201, created.content
    assert created.json()["id"] == 50
    changed = client.patch("/api/leaky-sales/50/", {"id": 99, "product": "Table"}, format="json")
    assert changed.status_code == 200, changed.content
    assert list(Sale.objects.values_list("id", "product")) == [(50, "Table")]


def test_the_role_sync_skips_a_database_without_the_role_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from karni.accounts import apps as accounts_apps

    calls: list[Any] = []
    monkeypatch.setattr("karni.accounts.roles.sync_roles", lambda: calls.append(1))
    config = django_apps.get_app_config("karni_accounts")
    accounts_apps.sync_roles_after_migrate(config, using="second", verbosity=0)
    assert calls == []
    with override_settings(KARNI_ROLES_AUTOSYNC=True):
        accounts_apps.sync_roles_after_migrate(config, using="default", verbosity=0)
    assert calls == [1]

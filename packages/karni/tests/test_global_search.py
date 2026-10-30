"""Cross-model search (experimental): ``class Karni: search`` and ``GET /api/search/``.

The catalog in :mod:`tests.searchapp` has four routed resources with four
access rules (public products, suppliers for signed-in users, notes for their
author, reports for staff) and one declared model without a viewset. The
suite runs on SQLite (icontains, the portable scores) and on PostgreSQL
(trigram similarity, the indexes, ``karni.W590``), with UUID and integer keys.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection, models
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.graph import MigrationGraph
from django.db.migrations.operations import AddIndex
from django.db.migrations.questioner import MigrationQuestioner
from django.db.migrations.state import ProjectState
from django.db.migrations.writer import MigrationWriter
from django.test import override_settings
from django.test.utils import CaptureQueriesContext, isolate_apps
from rest_framework.test import APIClient

from karni.accounts.permissions import assign_role
from karni.api.global_search import SCORE, TITLE, search_queryset, search_targets
from karni.api.routers import KarniRouter
from karni.checks import check_global_search, check_global_search_routes
from karni.exceptions import KarniImproperlyConfigured
from karni.fields import TrigramIndex
from karni.global_search import (
    SearchDeclaration,
    check_search_indexes,
    indexed_fields,
    search_declaration,
    search_index_failures,
    searchable_models,
)
from tests.searchapp.models import Note, Product, Region, Report, Supplier
from tests.searchapp.viewsets import ProductViewSet
from tests.testapp.models import TEST_PK

pytestmark = pytest.mark.django_db
POSTGRES = connection.vendor == "postgresql"
ROUTED = override_settings(
    ROOT_URLCONF="tests.searchapp.urls", KARNI_API_ROUTER="tests.searchapp.urls.get_router"
)


@pytest.fixture(autouse=True)
def _catalog_routes() -> Iterator[None]:
    with ROUTED:
        yield
    cache.clear()


def _user(email: str, *roles: str) -> Any:
    user = get_user_model().objects.create_user(email=email, password="a-strong-password-123")
    for role in roles:
        assign_role(user, role)
    return user


def _client(user: Any = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _search(client: APIClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/search/", params)
    assert response.status_code == 200, response.content
    data: dict[str, Any] = response.json()
    return data


def _groups(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {group["resource"]: group["hits"] for group in data["groups"]}


def _titles(hits: list[dict[str, Any]]) -> list[str]:
    return [hit["title"] for hit in hits]


@pytest.fixture
def catalog() -> dict[str, Any]:
    """A lamp in every resource, notes by two authors."""
    alice = _user("alice@example.com")
    bob = _user("bob@example.com")
    staff = _user("staff@example.com", "staff")
    acme = Supplier.objects.create(name="Lamp Works", city="Porto")
    Supplier.objects.create(name="Glassware Ltd", city="Lyon")
    Product.objects.create(name="Desk lamp", sku="DL-1", supplier=acme)
    Product.objects.create(name="Lamp", sku="LP-2")
    Product.objects.create(name="Lampshade", sku="LS-3")
    Product.objects.create(name="Chair", sku="CH-4")
    Note.objects.create(title="Lamp order for alice", created_by=alice)
    Note.objects.create(title="Lamp order for bob", created_by=bob)
    Report.objects.create(title="Lamp sales")
    Region.objects.create(name="Lamp coast")
    return {"alice": alice, "bob": bob, "staff": staff, "acme": acme}


# the declaration --------------------------------------------------------------------------


def test_the_declaration_fills_its_defaults() -> None:
    assert search_declaration(Product) == SearchDeclaration(
        ("name", "sku"), "name", "supplier__name", 2.0
    )
    assert search_declaration(Note) == SearchDeclaration(("title", "body"), "title", None, 1.0)
    assert search_declaration(get_user_model()) is None
    assert set(searchable_models()) >= {Supplier, Product, Note, Report, Region}


@isolate_apps("tests.searchapp")
@pytest.mark.parametrize(
    ("declared", "says"),
    [
        (["name"], "must be a dict"),
        ({"fields": ["name"], "sort": "name"}, "unknown keys: sort"),
        ({"title": "name"}, 'needs "fields"'),
        ({"fields": ["missing"]}, "not a field of Thing"),
        ({"fields": ["count"]}, "not a text field"),
        ({"fields": ["name"], "title": "owner__nope"}, "has no field 'nope'"),
        ({"fields": ["name"], "subtitle": "count__x"}, "not a relation to follow"),
        ({"fields": ["name"], "weight": 0}, "weight must be a number above 0"),
        ({"fields": ["name"], "weight": True}, "weight must be a number above 0"),
    ],
)
def test_a_malformed_declaration_is_e430(declared: Any, says: str) -> None:
    class Thing(models.Model):
        name = models.CharField(max_length=20)
        count = models.IntegerField(default=0)
        owner = models.ForeignKey(Supplier, null=True, on_delete=models.SET_NULL)

        class Karni:
            search = declared

        class Meta:
            app_label = "searchapp"

    with pytest.raises(KarniImproperlyConfigured) as raised:
        search_declaration(Thing)
    assert raised.value.code == "E430" and says in str(raised.value)
    (message,) = check_global_search([_config_of(Thing)])
    assert message.id == "karni.E430" and message.obj is Thing


def _config_of(model: type[models.Model]) -> Any:
    class Config:
        label = model._meta.app_label

        @staticmethod
        def get_models() -> list[type[models.Model]]:
            return [model]

    return Config()


def test_a_declared_model_without_a_routed_viewset_is_w591() -> None:
    messages = check_global_search_routes()
    assert [message.obj for message in messages] == [Region]
    assert messages[0].id == "karni.W591" and "no routed BaseViewSet" in messages[0].msg


def test_the_targets_follow_the_router_and_name_each_resource() -> None:
    targets = search_targets()
    assert [(target.resource, target.model) for target in targets] == [
        ("products", Product),
        ("suppliers", Supplier),
        ("notes", Note),
        ("reports", Report),
    ]
    assert targets[0].label == "Products"


# the indexes ------------------------------------------------------------------------------


def _trigram_indexes(model: type[models.Model]) -> dict[str, TrigramIndex]:
    return {
        index.fields[0]: index for index in model._meta.indexes if isinstance(index, TrigramIndex)
    }


def test_each_searched_field_gets_a_trigram_index() -> None:
    assert set(_trigram_indexes(Product)) == {"name", "sku"}
    assert set(_trigram_indexes(Note)) == {"title", "body"}
    assert indexed_fields(Product) == ["name", "sku"]
    index = _trigram_indexes(Product)["name"]
    assert index.opclasses == ("gin_trgm_ops",)
    assert index.name.startswith("searchapp_produc") and index.name.endswith("_trgm")
    assert len(index.name) <= index.max_name_length
    path, args, kwargs = index.deconstruct()
    assert path == "karni.fields.TrigramIndex" and "opclasses" not in kwargs
    assert TrigramIndex(*args, **kwargs) == index


def test_makemigrations_writes_the_indexes() -> None:
    after = ProjectState.from_apps(Product._meta.apps)
    before = after.clone()
    state = before.models[("searchapp", "product")]
    state.options["indexes"] = [
        index for index in state.options["indexes"] if not isinstance(index, TrigramIndex)
    ]
    questioner = MigrationQuestioner(specified_apps={"searchapp"})
    changes = MigrationAutodetector(before, after, questioner).changes(graph=MigrationGraph())
    (migration,) = changes["searchapp"]
    added = [op for op in migration.operations if isinstance(op, AddIndex)]
    assert {op.index.fields[0] for op in added} == {"name", "sku"}
    text = MigrationWriter(migration).as_string()
    assert "karni.fields.TrigramIndex(fields=['name'], name='searchapp_produc_" in text
    assert "import karni.fields" in text


def test_the_index_is_a_gin_trigram_index_on_postgresql_and_nothing_elsewhere() -> None:
    index = _trigram_indexes(Product)["name"]
    sql = str(index.create_sql(Product, connection.schema_editor()))
    if POSTGRES:
        assert "USING gin" in sql and "gin_trgm_ops" in sql
    else:
        assert sql.startswith("-- karni:") and "PostgreSQL-only" in sql


@pytest.mark.django_db(transaction=True)
def test_the_migration_operation_runs_on_this_database() -> None:
    """``AddIndex`` with a TrigramIndex: the index exists on PostgreSQL, nothing on SQLite."""
    index = _trigram_indexes(Supplier)["name"]
    state = ProjectState.from_apps(Supplier._meta.apps)
    operation = AddIndex("supplier", index)
    with connection.schema_editor() as editor:
        editor.remove_index(Supplier, index)
    assert index.name not in _index_names(Supplier)
    with connection.schema_editor() as editor:
        operation.database_forwards("searchapp", editor, state, state)
    assert (index.name in _index_names(Supplier)) is POSTGRES


def _index_names(model: type[models.Model]) -> set[str]:
    with connection.cursor() as cursor:
        found = connection.introspection.get_constraints(cursor, model._meta.db_table)
    return set(found)


# the check rule: a declared field without its index (PostgreSQL) ----------------------------


def test_w590_names_a_field_without_its_index_and_the_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "karni.management.commands.karni_check.entry_points", lambda **kw: []
    )  # the architecture hooks have their own tests
    assert check_search_indexes() == []
    if not POSTGRES:
        return  # the rule reads PostgreSQL's catalog: elsewhere there is nothing to check
    index = _trigram_indexes(Product)["sku"]
    with connection.schema_editor() as editor:
        editor.remove_index(Product, index)
    (message,) = check_search_indexes()
    assert message.id == "karni.W590" and message.obj is Product
    assert "Product.sku" in message.msg and "searchapp_product.sku" in message.msg
    assert "python manage.py makemigrations searchapp" in message.hint
    (line,) = search_index_failures()
    assert line.startswith("searchapp.Product: karni.W590:")
    with override_settings(SILENCED_SYSTEM_CHECKS=["karni.W590"]):
        assert check_search_indexes() == []
    out = StringIO()
    call_command("karni_check", stdout=out, stderr=StringIO())  # printed, not failed
    assert "search indexes: searchapp.Product: karni.W590:" in out.getvalue()
    assert "backend checks: ok" in out.getvalue()
    with connection.schema_editor() as editor:
        editor.add_index(Product, index)
    assert check_search_indexes() == []


# the endpoint -----------------------------------------------------------------------------


def test_a_hit_carries_what_links_it_to_its_page(catalog: dict[str, Any]) -> None:
    data = _search(_client(catalog["alice"]), q="desk")
    assert data["query"] == "desk"
    (group,) = data["groups"]
    assert group["resource"] == "products" and group["label"] == "Products"
    (hit,) = group["hits"]
    product = Product.objects.get(name="Desk lamp")
    assert hit == {
        "resource": "products",
        "id": product.pk if TEST_PK == "bigint" else str(product.pk),
        "title": "Desk lamp",
        "subtitle": "Lamp Works",
        "score": hit["score"],
    }
    assert isinstance(hit["id"], int if TEST_PK == "bigint" else str)
    assert hit["score"] > 0


def test_each_model_is_searched_under_its_own_access(catalog: dict[str, Any]) -> None:
    anonymous = _groups(_search(_client(), q="lamp"))
    assert set(anonymous) == {"products"}  # suppliers, notes and reports need a user or a role

    alice = _groups(_search(_client(catalog["alice"]), q="lamp"))
    assert set(alice) == {"products", "suppliers", "notes"}
    assert _titles(alice["notes"]) == ["Lamp order for alice"]  # bob's note is not listed

    staff = _groups(_search(_client(catalog["staff"]), q="lamp"))
    assert set(staff) == {"products", "suppliers", "reports"}  # staff wrote no note
    assert "regions" not in staff  # declared, but no viewset serves it


def test_one_query_per_model(catalog: dict[str, Any]) -> None:
    client = _client(catalog["alice"])
    with CaptureQueriesContext(connection) as queries:
        _search(client, q="lamp")
    for model in (Product, Supplier, Note, Report):
        table = model._meta.db_table
        reading = [q["sql"] for q in queries if f'FROM "{table}"' in q["sql"]]
        expected = 0 if model is Report else 1  # alice may not list reports: no query at all
        assert len(reading) == expected, (table, reading)


def test_the_weight_ranks_a_model_across_models(catalog: dict[str, Any]) -> None:
    data = _search(_client(catalog["staff"]), q="lamp")
    order = [group["resource"] for group in data["groups"]]
    assert order[0] == "products"  # weight 2
    assert order[-1] == "reports"  # weight 0.5
    for model, resource in ((Product, "products"), (Report, "reports")):
        declaration = search_declaration(model)
        assert declaration is not None
        raw = dict(
            search_queryset(model.objects.all(), "lamp", declaration).values_list(TITLE, SCORE)
        )
        for hit in _groups(data)[resource]:
            assert hit["score"] == pytest.approx(raw[hit["title"]] * declaration.weight, abs=1e-4)


def test_the_models_filter_and_its_unknown_names(catalog: dict[str, Any]) -> None:
    client = _client(catalog["alice"])
    assert set(_groups(_search(client, q="lamp", models="suppliers,notes"))) == {
        "suppliers",
        "notes",
    }
    assert set(_groups(_search(client, q="lamp", models=["notes"]))) == {"notes"}
    # A covered resource the caller may not list is absent, not an error.
    assert _search(client, q="lamp", models="reports")["groups"] == []
    refused = client.get("/api/search/", {"q": "lamp", "models": "products,regions"})
    assert refused.status_code == 400
    body = refused.json()
    assert body["code"] == "E431" and "regions" in body["detail"]
    assert body["resources"] == ["products", "suppliers", "notes", "reports"]


def test_the_limit_is_per_model_and_capped(catalog: dict[str, Any]) -> None:
    client = _client(catalog["alice"])
    groups = _groups(_search(client, q="lamp", limit=1))
    assert {resource: len(hits) for resource, hits in groups.items()} == {
        "products": 1,
        "suppliers": 1,
        "notes": 1,
    }
    assert len(_groups(_search(client, q="lamp"))["products"]) == 3  # the default (5) fits all
    with override_settings(KARNI_GLOBAL_SEARCH_MAX_LIMIT=2):
        assert len(_groups(_search(client, q="lamp", limit=50))["products"]) == 2
    assert len(_groups(_search(client, q="lamp", limit="many"))["products"]) == 3


@pytest.mark.parametrize("query", ["", " ", "l", " l "])
def test_an_empty_or_short_query_answers_no_groups(catalog: dict[str, Any], query: str) -> None:
    with CaptureQueriesContext(connection) as queries:
        data = _search(_client(catalog["alice"]), q=query)
    assert data == {"query": query.strip(), "groups": []}
    assert not any("searchapp_" in q["sql"] for q in queries)


def test_the_minimum_length_is_a_setting(catalog: dict[str, Any]) -> None:
    with override_settings(KARNI_GLOBAL_SEARCH_MIN_LENGTH=5):
        assert _search(_client(), q="lamp")["groups"] == []
    with override_settings(KARNI_GLOBAL_SEARCH_MIN_LENGTH=1):
        assert _search(_client(), q="c")["groups"] != []


def test_ranking_puts_the_closest_match_first(catalog: dict[str, Any]) -> None:
    hits = _groups(_search(_client(), q="lamp"))["products"]
    # PostgreSQL: the closest trigram set (a whole word beats a longer prefix).
    # SQLite: equal, then starts with, then contains.
    expected = ["Desk lamp", "Lampshade"] if POSTGRES else ["Lampshade", "Desk lamp"]
    expected.insert(0, "Lamp")
    assert _titles(hits) == expected
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True) and scores[0] > scores[-1]


@pytest.mark.skipif(POSTGRES, reason="the portable scores (SQLite and other databases)")
def test_sqlite_matches_by_icontains_with_portable_scores(catalog: dict[str, Any]) -> None:
    hits = _groups(_search(_client(), q="LAMP"))["products"]
    assert [(hit["title"], hit["score"]) for hit in hits] == [
        ("Lamp", 2.0),  # equals: 1, times the weight
        ("Lampshade", 1.5),  # starts with: 0.75
        ("Desk lamp", 1.0),  # contains: 0.5
    ]
    assert _search(_client(), q="lampp")["groups"] == []  # no similarity leg without pg_trgm
    assert _titles(_groups(_search(_client(), q="dl-1"))["products"]) == ["Desk lamp"]


@pytest.mark.skipif(not POSTGRES, reason="trigram similarity needs PostgreSQL (pg_trgm)")
def test_postgresql_ranks_by_trigram_similarity(catalog: dict[str, Any]) -> None:
    hits = _groups(_search(_client(), q="lamp"))["products"]
    assert hits[0]["title"] == "Lamp" and hits[0]["score"] == pytest.approx(2.0)
    # A typo matches by similarity, without containing the query.
    assert _titles(_groups(_search(_client(), q="lampp"))["products"])[0] == "Lamp"
    # The threshold is a setting.
    with override_settings(KARNI_GLOBAL_SEARCH_THRESHOLD=0.9):
        assert "products" not in _groups(_search(_client(), q="lampp"))
    # LIKE's wildcards in a query are plain characters.
    assert _search(_client(), q="l%p")["groups"] == []


def test_the_hook_builds_a_models_search_queryset(catalog: dict[str, Any]) -> None:
    class SkuSearch(ProductViewSet):
        """Only SKUs that start with L, titled by their SKU."""

        def global_search_queryset(
            self, queryset: Any, query: str, declaration: SearchDeclaration
        ) -> Any:
            found = super().global_search_queryset(queryset, query, declaration)
            return found.filter(sku__startswith="L").annotate(**{TITLE: models.F("sku")})

    def router() -> KarniRouter:
        custom = KarniRouter()
        custom.register("products", SkuSearch, basename="searchapp-product")
        return custom

    global _HOOK_ROUTER
    _HOOK_ROUTER = router
    with override_settings(KARNI_API_ROUTER=f"{__name__}._hook_router"):
        hits = _groups(_search(_client(), q="lamp"))["products"]
    assert _titles(hits) == ["LP-2", "LS-3"]


_HOOK_ROUTER: Any = None


def _hook_router() -> KarniRouter:
    router: KarniRouter = _HOOK_ROUTER()
    return router


def test_search_queryset_is_lazy_and_ordered(catalog: dict[str, Any]) -> None:
    declaration = search_declaration(Product)
    assert declaration is not None
    queryset = search_queryset(Product.objects.all(), "lamp", declaration)
    assert queryset.query.order_by == (f"-{SCORE}", TITLE, "pk")
    assert {TITLE, SCORE} <= set(queryset.query.annotations)


# the OpenAPI document ---------------------------------------------------------------------


def test_the_schema_documents_the_endpoint() -> None:
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    operation = schema["paths"]["/api/search/"]["get"]
    assert operation["operationId"] == "global_search"
    assert operation["x-karni-search"] == {
        "resources": ["products", "suppliers", "notes", "reports"]
    }
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"q", "models", "limit"}
    assert parameters["models"]["schema"]["items"]["enum"] == [
        "notes",
        "products",
        "reports",
        "suppliers",
    ]
    ok = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ok.endswith("/GlobalSearchResult")
    hit = schema["components"]["schemas"]["GlobalSearchHit"]["properties"]
    assert hit["id"] == {
        "oneOf": [{"type": "string"}, {"type": "integer"}],
        "description": hit["id"]["description"],
    }

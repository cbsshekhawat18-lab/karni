"""Prompt 1 coverage for Karni's model layer.

Spec: "pytest coverage for every behaviour: soft-delete manager, restore,
audit population under both WSGI and ASGI, UUID PK in relations", under the
constraints "Soft delete must not break related lookups, admin, or cascade
behaviour" and "Each mixin must be usable on its own, not only through
BaseModel".

The models live in ``tests.testapp`` (an installed app, so cascades and the
admin see real reverse relations): ``Stamp``, ``Entry``, ``Remark`` and
``Review`` use exactly one mixin each; ``Shelf`` → ``Book`` ↔ ``Label`` are
``BaseModel``\\ s. Not repeated here: single-model soft-delete details
(signals, ``alive()``/``dead()``, declaration flags) in ``tests/test_models.py``,
and the admin's soft-delete actions, autocomplete and FK widening for a
standalone ``SoftDeleteModel`` in ``tests/admin/test_soft_delete.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from asgiref.sync import async_to_sync, iscoroutinefunction
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.test import AsyncClient, Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from karni.managers import (
    AuditedQuerySet,
    BaseManager,
    BaseQuerySet,
    SoftDeleteManager,
    SoftDeleteQuerySet,
    TimestampedQuerySet,
)
from karni.middleware import CurrentUserMiddleware, current_user, get_current_user
from karni.models import AuditedModel, SoftDeleteModel, TimestampedModel, UUIDModel
from tests.testapp.models import (
    Book,
    Entry,
    Event,
    Label,
    Remark,
    Review,
    Shelf,
    Stamp,
    Tag,
    Venue,
)

pytestmark = pytest.mark.django_db

PASSWORD = "a-strong-password-123"
STARTS_AT = "2030-05-01T18:00:00Z"
#: The two plain views in tests/model_layer_views.py (sync and async).
AUDIT_VIEWS = ["model-layer-venue-sync", "model-layer-venue-async"]


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> Any:
    """Keep DRF's throttle counters (locmem cache) from leaking across tests."""
    yield
    cache.clear()


@pytest.fixture
def alice() -> Any:
    return get_user_model().objects.create_user(email="alice@example.com", password=PASSWORD)


@pytest.fixture
def bob() -> Any:
    return get_user_model().objects.create_user(email="bob@example.com", password=PASSWORD)


@pytest.fixture
def shelf() -> Shelf:
    return Shelf.objects.create(name="Fiction")


@pytest.fixture
def book(shelf: Shelf) -> Book:
    return Book.objects.create(shelf=shelf, title="Dune")


def _fields(model: type[models.Model]) -> set[str]:
    return {field.name for field in model._meta.concrete_fields}


def _bearer(user: Any) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return api


def _request_as(path: str, user: Any) -> HttpRequest:
    request = RequestFactory().get(path)
    request.user = user
    return request


# --- each mixin on its own ----------------------------------------------------


class TestUUIDModelAlone:
    def test_adds_only_a_random_uuid_primary_key(self) -> None:
        assert _fields(Stamp) == {"id", "value"}
        pk = Stamp._meta.pk
        assert isinstance(pk, models.UUIDField)
        assert pk.default is uuid.uuid4
        assert not pk.editable
        for attr in ("is_deleted", "restore", "hard_delete"):
            assert not hasattr(Stamp, attr), attr

    def test_rows_get_distinct_uuids_and_delete_is_real(self) -> None:
        first = Stamp.objects.create(value="a")
        second = Stamp.objects.create(value="b")
        assert isinstance(first.pk, uuid.UUID)
        assert first.pk != second.pk
        assert Stamp.objects.get(pk=str(first.pk)) == first

        first.delete()

        assert list(Stamp.objects.all()) == [second]


class TestTimestampedModelAlone:
    def test_adds_only_timestamps_and_their_queryset(self) -> None:
        assert _fields(Entry) == {"id", "created_at", "updated_at", "text"}
        assert not isinstance(Entry._meta.pk, models.UUIDField)
        queryset = Entry.objects.all()
        assert isinstance(queryset, TimestampedQuerySet)
        assert not isinstance(queryset, SoftDeleteQuerySet | AuditedQuerySet)

    def test_stamps_times_and_filters_by_them(self) -> None:
        now = timezone.now()
        old = Entry.objects.create(text="old")
        three_days_ago = now - timedelta(days=3)
        Entry.objects.filter(pk=old.pk).update(created_at=three_days_ago, updated_at=three_days_ago)
        old.refresh_from_db()
        new = Entry.objects.create(text="new")
        cutoff = now - timedelta(days=1)

        assert new.created_at is not None and new.updated_at is not None
        assert list(Entry.objects.created_since(cutoff)) == [new]
        assert list(Entry.objects.created_between(now - timedelta(days=4), cutoff)) == [old]
        assert list(Entry.objects.updated_since(cutoff)) == [new]
        assert list(Entry.objects.newest_first()) == [new, old]

        old.text = "touched"
        old.save()  # auto_now refreshes updated_at; created_at stays put
        assert set(Entry.objects.updated_since(cutoff)) == {old, new}
        assert list(Entry.objects.created_since(cutoff)) == [new]

        old.delete()
        assert list(Entry.objects.by_ids([old.pk, new.pk])) == [new]  # a real DELETE


class TestSoftDeleteModelAlone:
    def test_adds_only_deleted_at_and_the_soft_delete_manager(self) -> None:
        assert _fields(Review) == {"id", "deleted_at", "book", "stars"}
        assert not isinstance(Review._meta.pk, models.UUIDField)
        assert isinstance(Review.objects, SoftDeleteManager)
        assert Review._default_manager is Review.objects
        assert not isinstance(Review.objects.all(), TimestampedQuerySet | AuditedQuerySet)

    def test_manager_hides_deleted_rows_and_reaches_them_on_demand(self, book: Book) -> None:
        kept = Review.objects.create(book=book, stars=5)
        gone = Review.objects.create(book=book, stars=1)

        assert gone.delete() == (1, {"testapp.Review": 1})

        assert list(Review.objects.all()) == [kept]
        with pytest.raises(Review.DoesNotExist):
            Review.objects.get(pk=gone.pk)
        assert list(Review.objects.all_with_deleted()) == [kept, gone]
        assert list(Review.objects.deleted_only()) == [gone]
        assert list(Review.all_objects.all()) == [kept, gone]  # the unfiltered alias
        # Reaching deleted rows never makes delete() hard.
        Review.objects.all_with_deleted().delete()
        assert Review.objects.count() == 0
        assert Review.objects.all_with_deleted().count() == 2

    def test_instance_and_queryset_restore(self, book: Book) -> None:
        reviews = [Review.objects.create(book=book, stars=stars) for stars in (1, 2, 3)]
        assert Review.objects.all().delete() == (3, {"testapp.Review": 3})

        reviews[0].restore()
        assert list(Review.objects.all()) == reviews[:1]

        assert Review.objects.deleted_only().filter(stars=2).restore() == 1
        assert list(Review.objects.all()) == reviews[:2]
        assert list(Review.objects.deleted_only()) == reviews[2:]

        # Restoring alive rows is a no-op; bulk restore exists on querysets only.
        assert Review.objects.all().restore() == 0
        assert not hasattr(Review.objects, "restore")


class TestAuditedModelAlone:
    def test_adds_only_the_audit_user_fks(self) -> None:
        assert _fields(Remark) == {"id", "created_by", "updated_by", "text"}
        for name in ("created_by", "updated_by"):
            field = Remark._meta.get_field(name)
            assert field.remote_field.model is get_user_model(), name
            assert field.null and not field.editable, name
            assert field.remote_field.on_delete is models.SET_NULL, name
            assert field.remote_field.related_name == "+", name
        queryset = Remark.objects.all()
        assert isinstance(queryset, AuditedQuerySet)
        assert not isinstance(queryset, TimestampedQuerySet | SoftDeleteQuerySet)

    def test_stamps_users_and_filters_by_them(self, alice: Any, bob: Any) -> None:
        with current_user(alice):
            mine = Remark.objects.create(text="mine")
        with current_user(bob):
            theirs = Remark.objects.create(text="theirs")
            mine.text = "edited by bob"
            mine.save()

        mine.refresh_from_db()
        assert (mine.created_by, mine.updated_by) == (alice, bob)
        assert list(Remark.objects.created_by(alice)) == [mine]
        assert set(Remark.objects.updated_by(bob)) == {mine, theirs}
        assert list(Remark.objects.touched_by(alice)) == [mine]

        mine.delete()
        assert list(Remark.objects.all()) == [theirs]  # a real DELETE


# --- BaseModel: the four composed ---------------------------------------------


class TestBaseModelComposition:
    def test_is_all_four_mixins_with_one_composed_manager(self) -> None:
        for mixin in (UUIDModel, TimestampedModel, SoftDeleteModel, AuditedModel):
            assert issubclass(Shelf, mixin), mixin
        assert _fields(Shelf) == {
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "created_by",
            "updated_by",
            "name",
        }
        assert isinstance(Shelf._meta.pk, models.UUIDField)
        assert isinstance(Shelf.objects, BaseManager)
        assert Shelf._default_manager is Shelf.objects
        queryset = Shelf.objects.all()
        assert isinstance(queryset, BaseQuerySet)
        for queryset_class in (TimestampedQuerySet, SoftDeleteQuerySet, AuditedQuerySet):
            assert isinstance(queryset, queryset_class), queryset_class

    def test_queryset_helpers_chain_across_mixins(self, alice: Any, bob: Any) -> None:
        now = timezone.now()
        with current_user(alice):
            old = Shelf.objects.create(name="old")
            fresh_dead = Shelf.objects.create(name="fresh-dead")
            fresh_alive = Shelf.objects.create(name="fresh-alive")
        with current_user(bob):
            bobs_dead = Shelf.objects.create(name="bobs-dead")
        Shelf.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=10))
        Shelf.objects.by_ids([old.pk, fresh_dead.pk, bobs_dead.pk]).delete()
        cutoff = now - timedelta(days=1)

        everything = Shelf.objects.all_with_deleted()
        assert list(everything.created_since(cutoff).created_by(alice).dead()) == [fresh_dead]
        assert list(everything.dead().created_by(alice).created_since(cutoff)) == [fresh_dead]
        # objects is alive-only, so the same chain from it has nothing dead...
        assert not Shelf.objects.created_since(cutoff).created_by(alice).dead().exists()
        assert list(Shelf.objects.created_since(cutoff).touched_by(alice)) == [fresh_alive]
        # ...while deleted_only() composes with every mixin's helpers.
        assert list(Shelf.objects.deleted_only().created_by(alice).newest_first()) == [
            fresh_dead,
            old,
        ]

    def test_delete_and_restore_record_who_did_it(self, alice: Any, bob: Any) -> None:
        with current_user(alice):
            shelf = Shelf.objects.create(name="audited")
        with current_user(bob):
            shelf.delete()

        stored = Shelf.objects.all_with_deleted().get(pk=shelf.pk)
        assert stored.is_deleted
        assert (stored.created_by, stored.updated_by) == (alice, bob)

        with current_user(alice):
            stored.restore()
        restored = Shelf.objects.get(pk=shelf.pk)
        assert restored.deleted_at is None
        assert (restored.created_by, restored.updated_by) == (alice, alice)


# --- soft delete vs. related lookups ------------------------------------------


class TestRelatedLookups:
    def test_reverse_fk_and_prefetch_hide_soft_deleted_children(self, shelf: Shelf) -> None:
        kept = Book.objects.create(shelf=shelf, title="kept")
        Book.objects.create(shelf=shelf, title="gone").delete()

        assert list(shelf.books.all()) == [kept]
        assert shelf.books.count() == 1
        prefetched = Shelf.objects.prefetch_related("books").get(pk=shelf.pk)
        assert list(prefetched.books.all()) == [kept]

    def test_m2m_hides_soft_deleted_rows_on_both_sides(self, shelf: Shelf) -> None:
        book = Book.objects.create(shelf=shelf, title="book")
        other = Book.objects.create(shelf=shelf, title="other")
        kept = Label.objects.create(name="kept")
        gone = Label.objects.create(name="gone")
        book.labels.add(kept, gone)
        other.labels.add(kept)

        gone.delete()
        other.delete()

        assert list(book.labels.all()) == [kept]
        assert list(kept.books.all()) == [book]
        # The links themselves are untouched, so a restore brings them back.
        assert Book.labels.through.objects.count() == 3
        gone.restore()
        assert set(book.labels.all()) == {kept, gone}

    def test_related_managers_reach_deleted_rows_within_their_relation_only(self) -> None:
        """Regression: ``all_with_deleted()``/``deleted_only()`` keep the relation filter."""
        mine = Shelf.objects.create(name="mine")
        other = Shelf.objects.create(name="other")
        alive = Book.objects.create(shelf=mine, title="alive")
        dead = Book.objects.create(shelf=mine, title="dead")
        stranger = Book.objects.create(shelf=other, title="stranger")
        dead.delete()
        stranger.delete()

        assert set(mine.books.all_with_deleted()) == {alive, dead}
        assert list(mine.books.deleted_only()) == [dead]
        assert mine.books.deleted_only().restore() == 1
        assert Book.objects.deleted_only().get() == stranger

        # Many-to-many related managers likewise.
        x, y, z = (Label.objects.create(name=name) for name in "xyz")
        alive.labels.add(x, y)
        y.delete()
        z.delete()
        assert set(alive.labels.all_with_deleted()) == {x, y}
        assert list(alive.labels.deleted_only()) == [y]

        # And a standalone SoftDeleteModel's reverse manager.
        first = Review.objects.create(book=alive)
        second = Review.objects.create(book=alive)
        Review.objects.create(book=stranger).delete()
        second.delete()
        assert list(alive.reviews.all_with_deleted()) == [first, second]
        assert list(alive.reviews.deleted_only()) == [second]

    def test_forward_fk_still_resolves_a_soft_deleted_parent(
        self, shelf: Shelf, book: Book
    ) -> None:
        shelf.delete()

        reloaded = Book.objects.get(pk=book.pk)  # no cascade: the child is alive
        assert reloaded.shelf == shelf
        assert reloaded.shelf.is_deleted
        assert Book.objects.select_related("shelf").get(pk=book.pk).shelf.is_deleted

        # A standalone SoftDeleteModel pointing at a soft-deleted BaseModel too.
        review = Review.objects.create(book=book)
        book.delete()
        assert Review.objects.get(pk=review.pk).book.is_deleted

    def test_cross_relation_filters_are_explicit_about_deleted_rows(self, shelf: Shelf) -> None:
        # Joins never go through a manager, so a filter spanning a relation
        # matches soft-deleted rows unless it says otherwise (as with any
        # Django default manager) — spell it out with deleted_at__isnull.
        survivor = Book.objects.create(shelf=shelf, title="survivor")
        Book.objects.create(shelf=shelf, title="gone").delete()
        assert list(Shelf.objects.filter(books__title="gone")) == [shelf]
        assert not Shelf.objects.filter(
            books__title="gone", books__deleted_at__isnull=True
        ).exists()

        shelf.delete()
        assert list(Book.objects.filter(shelf__name="Fiction")) == [survivor]
        assert not Book.objects.filter(
            shelf__name="Fiction", shelf__deleted_at__isnull=True
        ).exists()


# --- cascades -----------------------------------------------------------------


class TestCascades:
    def test_hard_delete_cascades_over_soft_deleted_children(self, shelf: Shelf) -> None:
        alive = Book.objects.create(shelf=shelf, title="alive")
        dead = Book.objects.create(shelf=shelf, title="dead")
        label = Label.objects.create(name="sf")
        alive.labels.add(label)
        dead.labels.add(label)
        Review.objects.create(book=alive)
        Review.objects.create(book=dead).delete()
        dead.delete()

        count, per_model = shelf.hard_delete()

        assert per_model == {
            "testapp.Shelf": 1,
            "testapp.Book": 2,
            "testapp.Review": 2,
            "testapp.Book_labels": 2,
        }
        assert count == 7
        for model in (Shelf, Book, Review):
            assert not model.objects.all_with_deleted().exists(), model
        assert not Book.labels.through.objects.exists()
        assert Label.objects.get() == label  # M2M targets are never cascaded

    def test_queryset_hard_delete_reaches_soft_deleted_rows_and_cascades(
        self, shelf: Shelf, book: Book
    ) -> None:
        Review.objects.create(book=book)
        shelf.delete()

        count, per_model = Shelf.objects.deleted_only().hard_delete()

        assert per_model == {"testapp.Shelf": 1, "testapp.Book": 1, "testapp.Review": 1}
        assert count == 3
        assert not Book.objects.all_with_deleted().exists()

    def test_audit_fks_outlive_a_soft_deleted_user_and_null_on_hard_delete(
        self, alice: Any
    ) -> None:
        with current_user(alice):
            shelf = Shelf.objects.create(name="audited")

        alice.delete()  # soft: the reference stays and still resolves
        shelf.refresh_from_db()
        assert shelf.created_by_id == alice.pk
        assert shelf.created_by.is_deleted

        alice.hard_delete()  # real: SET_NULL, the audited row survives
        shelf.refresh_from_db()
        assert shelf.created_by is None
        assert shelf.updated_by is None


# --- UUID primary keys in relations -------------------------------------------


class TestUUIDPrimaryKeysInRelations:
    def test_fk_to_a_uuid_pk(self, shelf: Shelf, book: Book) -> None:
        assert Book._meta.get_field("shelf").target_field is Shelf._meta.pk
        assert isinstance(book.shelf_id, uuid.UUID)
        assert book.shelf_id == shelf.pk
        lookups: list[dict[str, Any]] = [
            {"shelf": shelf},
            {"shelf": shelf.pk},
            {"shelf_id": str(shelf.pk)},
            {"shelf__pk__in": [str(shelf.pk)]},
        ]
        for lookup in lookups:
            assert list(Book.objects.filter(**lookup)) == [book], lookup
        assert Book.objects.select_related("shelf").get(pk=str(book.pk)).shelf == shelf

    def test_integer_pk_model_pointing_at_a_uuid_pk(self, book: Book) -> None:
        review = Review.objects.create(book=book)
        assert isinstance(review.pk, int)
        assert isinstance(review.book_id, uuid.UUID)
        assert list(Review.objects.filter(book_id=str(book.pk))) == [review]
        assert list(book.reviews.all()) == [review]

    def test_m2m_between_uuid_pks(self, book: Book) -> None:
        first = Label.objects.create(name="first")
        second = Label.objects.create(name="second")
        book.labels.add(first, second.pk)  # instances or raw UUIDs

        links = list(Book.labels.through.objects.filter(book=book))
        assert {link.label_id for link in links} == {first.pk, second.pk}
        assert all(isinstance(link.label_id, uuid.UUID) for link in links)
        assert list(Book.objects.filter(labels=first)) == [book]
        assert list(Book.objects.filter(labels__pk__in=[str(second.pk)])) == [book]
        assert list(first.books.all()) == [book]

        book.labels.remove(first)
        assert list(book.labels.all()) == [second]

    def test_by_ids_accepts_uuids_and_their_strings(self) -> None:
        a, b, _c = (Shelf.objects.create(name=name) for name in "abc")
        assert set(Shelf.objects.by_ids([a.pk, str(b.pk)])) == {a, b}

    def test_relations_serialize_and_filter_through_the_api(self, alice: Any) -> None:
        venue = Venue.objects.create(name="Arena", city="Berlin")
        elsewhere = Venue.objects.create(name="Club", city="Hamburg")
        tag = Tag.objects.create(name="music")
        Event.objects.create(title="Elsewhere", starts_at=timezone.now(), venue=elsewhere)
        api = _bearer(alice)
        list_url = reverse("testapp-event-list")

        response = api.post(
            list_url,
            {
                "title": "Show",
                "starts_at": STARTS_AT,
                "venue": str(venue.pk),
                "tags": [str(tag.pk)],
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        body = response.json()
        assert uuid.UUID(body["id"])
        assert body["venue"] == str(venue.pk)
        assert body["tags"] == [str(tag.pk)]
        assert body["created_by"] == str(alice.pk)
        assert "deleted_at" not in body

        def ids(params: dict[str, str]) -> set[str]:
            listed = api.get(list_url, params)
            assert listed.status_code == 200, listed.data
            return {row["id"] for row in listed.json()["results"]}

        assert ids({"venue": str(venue.pk)}) == {body["id"]}
        assert ids({"created_by": str(alice.pk)}) == {body["id"]}
        assert api.get(list_url, {"venue": "not-a-uuid"}).status_code == 400


# --- audit population ---------------------------------------------------------


def test_current_user_middleware_runs_after_authentication() -> None:
    middleware = list(settings.MIDDLEWARE)
    assert middleware.index("karni.middleware.CurrentUserMiddleware") > middleware.index(
        "django.contrib.auth.middleware.AuthenticationMiddleware"
    )


class TestAuditWithoutARequest:
    def test_nothing_is_stamped(self) -> None:
        assert get_current_user() is None
        shelf = Shelf.objects.create(name="cron")
        assert shelf.created_by is None
        assert shelf.updated_by is None

    def test_current_user_override_stamps_then_resets(self, alice: Any) -> None:
        with current_user(alice):
            assert get_current_user() == alice
            shelf = Shelf.objects.create(name="task")
        assert get_current_user() is None
        shelf.refresh_from_db()
        assert (shelf.created_by, shelf.updated_by) == (alice, alice)

    def test_update_moves_updated_by_and_keeps_created_by(self, alice: Any, bob: Any) -> None:
        with current_user(alice):
            shelf = Shelf.objects.create(name="draft")
        with current_user(bob):
            shelf.name = "renamed"
            shelf.save()
        shelf.refresh_from_db()
        assert (shelf.created_by, shelf.updated_by) == (alice, bob)

        shelf.save()  # no current user: existing stamps are never cleared
        shelf.refresh_from_db()
        assert (shelf.created_by, shelf.updated_by) == (alice, bob)

    def test_update_fields_save_still_persists_updated_by(self, alice: Any, bob: Any) -> None:
        with current_user(alice):
            shelf = Shelf.objects.create(name="draft")
        with current_user(bob):
            shelf.name = "partial"
            shelf.save(update_fields=["name"])

        stored = Shelf.objects.get(pk=shelf.pk)
        assert stored.name == "partial"
        assert (stored.created_by, stored.updated_by) == (alice, bob)

    def test_an_explicit_created_by_is_never_overwritten(self, alice: Any, bob: Any) -> None:
        with current_user(bob):
            shelf = Shelf.objects.create(name="imported", created_by=alice)
        assert (shelf.created_by, shelf.updated_by) == (alice, bob)

    def test_override_none_suppresses_stamping_inside_a_request(self, alice: Any) -> None:
        def view(request: HttpRequest) -> HttpResponse:
            with current_user(None):
                Shelf.objects.create(name="system")
            Shelf.objects.create(name="user")
            return HttpResponse()

        CurrentUserMiddleware(view)(_request_as("/", alice))

        assert Shelf.objects.get(name="system").created_by is None
        assert Shelf.objects.get(name="user").created_by == alice
        assert get_current_user() is None  # the middleware reset its context var

    def test_anonymous_request_users_are_never_stamped(self) -> None:
        seen: list[Any] = []

        def view(request: HttpRequest) -> HttpResponse:
            seen.append(get_current_user())
            return HttpResponse()

        CurrentUserMiddleware(view)(_request_as("/", AnonymousUser()))
        assert seen == [None]


class TestAuditUnderWSGI:
    """Django's test ``Client`` runs the full sync middleware stack."""

    @pytest.mark.parametrize("url_name", AUDIT_VIEWS)
    def test_session_user_is_stamped(self, client: Client, alice: Any, url_name: str) -> None:
        client.force_login(alice)

        response = client.post(reverse(url_name), {"name": "wsgi"})

        assert response.status_code == 201
        venue = Venue.objects.get(pk=response.json()["id"])
        assert (venue.created_by, venue.updated_by) == (alice, alice)

    def test_anonymous_request_stamps_nobody(self, client: Client) -> None:
        response = client.post(reverse(AUDIT_VIEWS[0]), {"name": "anonymous"})

        assert response.status_code == 201
        venue = Venue.objects.get(pk=response.json()["id"])
        assert (venue.created_by, venue.updated_by) == (None, None)


class TestAuditUnderASGI:
    """``AsyncClient`` runs the full async middleware stack (sync and async views)."""

    @pytest.mark.parametrize("url_name", AUDIT_VIEWS)
    def test_session_user_is_stamped(self, alice: Any, url_name: str) -> None:
        async def send() -> Any:
            async_client = AsyncClient()
            await async_client.aforce_login(alice)
            return await async_client.post(reverse(url_name), {"name": "asgi"})

        # async_to_sync (as Django's async TestCase does) keeps the ORM's
        # thread-sensitive calls on this thread's connection and transaction.
        response = async_to_sync(send)()

        assert response.status_code == 201
        venue = Venue.objects.get(pk=response.json()["id"])
        assert (venue.created_by, venue.updated_by) == (alice, alice)

    def test_concurrent_tasks_each_see_their_own_user(self, alice: Any, bob: Any) -> None:
        seen: dict[str, Any] = {}

        async def run_both() -> None:
            barrier = asyncio.Barrier(2)

            async def view(request: HttpRequest) -> HttpResponse:
                await barrier.wait()  # both requests are inside the middleware now
                seen[request.path] = get_current_user()
                await Venue.objects.acreate(name=request.path, city="gather")
                return HttpResponse(status=201)

            middleware = CurrentUserMiddleware(view)
            assert iscoroutinefunction(middleware)
            await asyncio.gather(
                middleware(_request_as("/alice/", alice)),
                middleware(_request_as("/bob/", bob)),
            )
            assert get_current_user() is None  # nothing leaked into the caller

        async_to_sync(run_both)()

        assert seen == {"/alice/": alice, "/bob/": bob}
        assert Venue.objects.get(name="/alice/").created_by == alice
        assert Venue.objects.get(name="/bob/").created_by == bob


class TestAuditUnderDRFJWT:
    def test_jwt_user_is_stamped_although_it_authenticates_inside_the_view(
        self, alice: Any, bob: Any
    ) -> None:
        # No session: AuthenticationMiddleware sees AnonymousUser; DRF
        # authenticates the bearer token later, inside the view.
        response = _bearer(alice).post(
            reverse("testapp-event-list"),
            {"title": "Launch", "starts_at": STARTS_AT, "created_by": str(bob.pk)},
            format="json",
        )
        assert response.status_code == 201, response.data
        event = Event.objects.get(pk=response.data["id"])
        # The JWT user is stamped; the client-sent created_by is read-only.
        assert (event.created_by, event.updated_by) == (alice, alice)

        response = _bearer(bob).patch(
            reverse("testapp-event-detail", kwargs={"pk": str(event.pk)}),
            {"title": "Relaunch"},
            format="json",
        )
        assert response.status_code == 200, response.data
        event.refresh_from_db()
        assert (event.created_by, event.updated_by) == (alice, bob)
        assert response.json()["created_by"] == str(alice.pk)
        assert response.json()["updated_by"] == str(bob.pk)


# --- the user model is soft-delete aware --------------------------------------


def test_soft_deleted_users_are_hidden_and_cannot_authenticate(alice: Any) -> None:
    user_model = get_user_model()

    alice.delete()

    assert not user_model.objects.filter(pk=alice.pk).exists()
    assert user_model.objects.all_with_deleted().get(pk=alice.pk).is_deleted
    with pytest.raises(user_model.DoesNotExist):
        user_model.objects.get_by_natural_key(alice.email)
    assert authenticate(email=alice.email, password=PASSWORD) is None
    response = _bearer(alice).post(
        reverse("testapp-event-list"), {"title": "x", "starts_at": STARTS_AT}, format="json"
    )
    assert response.status_code == 401

    user_model.objects.all_with_deleted().get(pk=alice.pk).restore()
    assert authenticate(email=alice.email, password=PASSWORD) == alice


# --- admin --------------------------------------------------------------------


class TestAdmin:
    """BaseModel changelist scoping and each mixin alone in the derived admin.

    The standalone ``SoftDeleteModel`` changelist (scoping, facets, restore /
    hard-delete actions) is covered by ``tests/admin/test_soft_delete.py``.
    """

    def test_base_model_changelist_is_alive_by_default(self, admin_client: Client) -> None:
        Shelf.objects.create(name="kept")
        Shelf.objects.create(name="gone").delete()
        url = reverse("admin:testapp_shelf_changelist")

        def names(params: dict[str, str]) -> set[str]:
            response = admin_client.get(url, params)
            assert response.status_code == 200
            return {shelf.name for shelf in response.context["cl"].queryset}

        assert names({}) == {"kept"}
        assert names({"deleted": "deleted"}) == {"gone"}
        assert names({"deleted": "all"}) == {"kept", "gone"}

    @pytest.mark.parametrize("model_name", ["stamp", "entry", "remark", "review", "book"])
    def test_each_mixin_alone_gets_a_working_changelist_and_change_form(
        self, admin_client: Client, book: Book, model_name: str
    ) -> None:
        make = {
            "stamp": lambda: Stamp.objects.create(value="v"),
            "entry": lambda: Entry.objects.create(text="t"),
            "remark": lambda: Remark.objects.create(text="r"),
            "review": lambda: Review.objects.create(book=book),
            "book": lambda: book,
        }
        row = make[model_name]()

        changelist = admin_client.get(reverse(f"admin:testapp_{model_name}_changelist"))
        assert changelist.status_code == 200
        assert row in changelist.context["cl"].queryset
        change = admin_client.get(reverse(f"admin:testapp_{model_name}_change", args=[row.pk]))
        assert change.status_code == 200

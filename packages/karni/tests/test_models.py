"""Tests for :mod:`karni.models`: ``BaseModel`` and the soft-delete primitives.

The concrete models used here are private to this module: they carry an
explicit ``app_label`` that is *not* in ``INSTALLED_APPS`` (so ``makemigrations``
and admin autodiscovery never see them) and their tables are created directly
with the schema editor in a module-scoped fixture. This keeps the core model
tests independent of every other test app in the suite.
"""

from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from django.db import connection, models
from django.db.models.signals import post_delete, pre_delete

from karni.models import BaseModel, SoftDeleteManager, SoftDeleteModel, SoftDeleteQuerySet

TEST_APP_LABEL = "karni_tests_models"


class Author(BaseModel):
    """Concrete ``BaseModel`` used only by this module."""

    name = models.CharField(max_length=50)

    class Meta:
        app_label = TEST_APP_LABEL


class Post(SoftDeleteModel):
    """Concrete ``SoftDeleteModel`` with an FK parent for related-manager tests."""

    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="posts")
    title = models.CharField(max_length=50)

    class Meta(SoftDeleteModel.Meta):
        app_label = TEST_APP_LABEL


class Comment(BaseModel):
    """Concrete ``BaseModel`` pointing *at* a soft-delete model."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    text = models.CharField(max_length=50)

    class Meta:
        app_label = TEST_APP_LABEL


@pytest.fixture(scope="module")
def model_tables(django_db_setup: Any, django_db_blocker: Any) -> Iterator[None]:
    """Create (and afterwards drop) this module's model tables."""
    with django_db_blocker.unblock(), connection.schema_editor() as editor:
        editor.create_model(Author)
        editor.create_model(Post)
        editor.create_model(Comment)
    yield
    with django_db_blocker.unblock(), connection.schema_editor() as editor:
        editor.delete_model(Comment)
        editor.delete_model(Post)
        editor.delete_model(Author)


@contextmanager
def capture_deletion_signals(sender: type[models.Model]) -> Iterator[list[str]]:
    """Record which deletion signals fire for ``sender`` inside the block."""
    seen: list[str] = []

    def on_pre_delete(sender: Any, **kwargs: Any) -> None:
        seen.append("pre_delete")

    def on_post_delete(sender: Any, **kwargs: Any) -> None:
        seen.append("post_delete")

    pre_delete.connect(on_pre_delete, sender=sender)
    post_delete.connect(on_post_delete, sender=sender)
    try:
        yield seen
    finally:
        pre_delete.disconnect(on_pre_delete, sender=sender)
        post_delete.disconnect(on_post_delete, sender=sender)


# --- declaration-level checks (no database) ----------------------------------


def test_base_model_is_abstract() -> None:
    assert BaseModel._meta.abstract is True


def test_base_model_field_definitions() -> None:
    id_field = Author._meta.get_field("id")
    assert isinstance(id_field, models.UUIDField)
    assert id_field.primary_key is True
    assert id_field.editable is False
    assert id_field.default is uuid.uuid4

    created = Author._meta.get_field("created_at")
    assert isinstance(created, models.DateTimeField)
    assert created.auto_now_add is True
    assert created.db_index is True

    updated = Author._meta.get_field("updated_at")
    assert isinstance(updated, models.DateTimeField)
    assert updated.auto_now is True


def test_soft_delete_model_declaration() -> None:
    assert SoftDeleteModel._meta.abstract is True

    deleted = Post._meta.get_field("deleted_at")
    assert isinstance(deleted, models.DateTimeField)
    assert deleted.null is True
    assert deleted.blank is True
    assert deleted.db_index is True

    # objects is the default manager (related descriptors hide deleted rows);
    # a Meta subclassing SoftDeleteModel.Meta keeps default_manager_name.
    assert Post._meta.default_manager_name == "objects"
    assert Post._default_manager is Post.objects
    assert isinstance(Post.objects, SoftDeleteManager)
    assert not isinstance(Post.all_objects, SoftDeleteManager)
    assert isinstance(Post.all_objects.all(), SoftDeleteQuerySet)


def test_bulk_delete_exists_only_on_querysets() -> None:
    # queryset_only=True keeps delete/hard_delete off both managers:
    # Post.objects.delete() must not exist — deletion always goes through a
    # queryset (Post.objects.all().delete()).
    assert not hasattr(Post.objects, "delete")
    assert not hasattr(Post.objects, "hard_delete")
    assert not hasattr(Post.all_objects, "delete")
    assert not hasattr(Post.all_objects, "hard_delete")
    # ...while the filtering helpers are copied onto the managers.
    assert hasattr(Post.objects, "alive")
    assert hasattr(Post.all_objects, "dead")


def test_queryset_and_instance_method_flags() -> None:
    assert SoftDeleteQuerySet.delete.queryset_only is True  # type: ignore[attr-defined]
    assert SoftDeleteQuerySet.delete.alters_data is True  # type: ignore[attr-defined]
    assert SoftDeleteQuerySet.hard_delete.queryset_only is True  # type: ignore[attr-defined]
    assert SoftDeleteQuerySet.hard_delete.alters_data is True  # type: ignore[attr-defined]
    assert SoftDeleteModel.delete.alters_data is True  # type: ignore[attr-defined]
    assert SoftDeleteModel.hard_delete.alters_data is True  # type: ignore[attr-defined]
    assert SoftDeleteModel.restore.alters_data is True  # type: ignore[attr-defined]


def test_soft_delete_managers_stay_out_of_migrations() -> None:
    assert SoftDeleteManager.use_in_migrations is False
    assert type(Post.all_objects).use_in_migrations is False


def test_instance_delete_keeps_django_signature() -> None:
    parameters = inspect.signature(SoftDeleteModel.delete).parameters
    assert list(parameters) == ["self", "using", "keep_parents"]
    assert parameters["using"].default is None
    assert parameters["keep_parents"].default is False


# --- BaseModel behaviour ------------------------------------------------------


@pytest.mark.django_db
def test_uuid_pk_and_audit_timestamps(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    assert isinstance(author.id, uuid.UUID)
    assert author.created_at is not None
    assert author.updated_at is not None

    first_updated = author.updated_at
    time.sleep(0.005)  # sqlite stores microseconds; guarantee a distinct stamp
    author.name = "Ada L."
    author.save()
    author.refresh_from_db()
    assert author.updated_at > first_updated
    assert author.created_at < author.updated_at


@pytest.mark.django_db
def test_uuid_pks_are_random_per_row(model_tables: None) -> None:
    first = Author.objects.create(name="a")
    second = Author.objects.create(name="b")
    assert first.id != second.id


# --- soft-delete behaviour ----------------------------------------------------


@pytest.mark.django_db
def test_instance_delete_is_soft(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(author=author, title="hello")

    result = post.delete()

    assert result == (1, {Post._meta.label: 1})
    assert post.is_deleted is True
    assert post.deleted_at is not None
    assert Post.objects.count() == 0
    assert Post.all_objects.count() == 1
    # save() ran, so auto_now refreshed updated_at alongside deleted_at.
    stored = Post.all_objects.get(pk=post.pk)
    assert stored.deleted_at is not None
    assert stored.updated_at >= stored.deleted_at


@pytest.mark.django_db
def test_restore_brings_a_row_back(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(author=author, title="hello")
    post.delete()

    post.restore()

    assert post.is_deleted is False
    assert post.deleted_at is None
    assert Post.objects.filter(pk=post.pk).exists()


@pytest.mark.django_db
def test_queryset_delete_is_soft_and_reports_counts(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    Post.objects.create(author=author, title="one")
    Post.objects.create(author=author, title="two")

    result = Post.objects.all().delete()

    assert result == (2, {"karni_tests_models.Post": 2})
    assert Post.objects.count() == 0
    assert Post.all_objects.count() == 2
    assert Post.all_objects.dead().count() == 2


@pytest.mark.django_db
def test_all_objects_delete_is_still_soft(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(author=author, title="one")
    post.delete()
    Post.objects.create(author=author, title="two")

    result = Post.all_objects.all().delete()

    assert result[0] == 2  # matches every row, including the already-deleted one
    assert Post.objects.count() == 0
    assert Post.all_objects.count() == 2


@pytest.mark.django_db
def test_hard_delete_really_removes(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(author=author, title="one")

    post.hard_delete()

    assert Post.all_objects.count() == 0


@pytest.mark.django_db
def test_queryset_hard_delete_really_removes(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    Post.objects.create(author=author, title="one")
    Post.objects.create(author=author, title="two")

    count, per_model = Post.all_objects.all().hard_delete()

    assert count == 2
    assert per_model == {"karni_tests_models.Post": 2}
    assert Post.all_objects.count() == 0


@pytest.mark.django_db
def test_alive_and_dead_filters(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    alive = Post.objects.create(author=author, title="alive")
    dead = Post.objects.create(author=author, title="dead")
    dead.delete()

    assert list(Post.all_objects.alive()) == [alive]
    assert list(Post.all_objects.dead()) == [dead]
    # objects already excludes deleted rows, so its dead() is always empty.
    assert Post.objects.dead().count() == 0


@pytest.mark.django_db
def test_related_descriptor_hides_deleted_rows(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    kept = Post.objects.create(author=author, title="kept")
    gone = Post.objects.create(author=author, title="gone")
    gone.delete()

    assert list(author.posts.all()) == [kept]


@pytest.mark.django_db
def test_fk_access_still_resolves_a_deleted_target(model_tables: None) -> None:
    # Django's base manager is unfiltered, so existing references to a
    # soft-deleted row keep resolving (the admin change form relies on this).
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(author=author, title="one")
    comment = Comment.objects.create(post=post, text="hi")
    post.delete()

    reloaded = Comment.objects.get(pk=comment.pk)
    assert reloaded.post.pk == post.pk
    assert reloaded.post.is_deleted is True


@pytest.mark.django_db
def test_soft_delete_sends_no_deletion_signals(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(author=author, title="one")

    with capture_deletion_signals(Post) as seen:
        post.delete()
        Post.all_objects.all().delete()
    assert seen == []


@pytest.mark.django_db
def test_hard_delete_sends_deletion_signals(model_tables: None) -> None:
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(author=author, title="one")

    with capture_deletion_signals(Post) as seen:
        post.hard_delete()
    assert seen == ["pre_delete", "post_delete"]


@pytest.mark.django_db
def test_soft_delete_does_not_cascade(model_tables: None) -> None:
    # Documented semantics: a soft delete touches only the row itself —
    # related rows survive and keep referencing the (soft-deleted) target.
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(author=author, title="one")
    comment = Comment.objects.create(post=post, text="hi")

    post.delete()

    assert Comment.objects.filter(pk=comment.pk).exists()
    assert Comment.objects.get(pk=comment.pk).post_id == post.pk

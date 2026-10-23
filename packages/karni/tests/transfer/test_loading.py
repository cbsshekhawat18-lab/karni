"""``karni load`` (karni.transfer.loading): content by natural key, idempotent, one transaction."""

from __future__ import annotations

import io
import json
import re
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import CommandError, call_command

from karni.audit.models import ChangeBatch
from karni.transfer.loading import ContentImporter, LoadError, load_content
from tests.contentapp.models import Category, Member, Project, ProjectImage, Service, Slide
from tests.testapp.models import Event

pytestmark = pytest.mark.django_db


def _png() -> bytes:
    """A one-pixel PNG that Pillow reads, as the API's image validation does."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(buffer, "PNG")
    return buffer.getvalue()


PNG = _png()


@pytest.fixture(autouse=True)
def _media(tmp_path: Path, settings: Any) -> None:
    """Uploads of one test never show up in another."""
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _site() -> dict[str, Any]:
    return {
        # Members name projects that come later in the file.
        "contentapp.Member": [
            {
                "name": "Ada",
                "role": "Founder",
                "photo": "img/ada.png",
                "projects": ["nexus", "hillside"],
            }
        ],
        "contentapp.Service": [
            {"slug": "design", "title": "Design", "image": "img/design.png"},
            {"slug": "build", "title": "Build", "image": ""},
        ],
        "contentapp.Category": [
            {"slug": "homes", "name": "Homes", "key_services": ["design", "build"]},
        ],
        "contentapp.Project": [
            {
                "slug": "nexus",
                "title": "Nexus",
                "year": 2021,
                "published": True,
                "category": "homes",
                "services": ["design"],
                "image": "img/nexus.png",
                "gallery": [
                    {"image": "img/nexus-1.png", "alt": "Street"},
                    {"image": "img/nexus-2.png", "alt": "Garden"},
                    {"image": "img/nexus-3.png", "alt": "Plan"},
                ],
            },
            {"slug": "hillside", "title": "Hillside", "category": None, "services": []},
        ],
        "contentapp.Slide": [
            {"placement": "home", "service": None, "position": 1, "heading": "Welcome"},
            {"placement": "service", "service": "design", "position": 1, "heading": "Design"},
        ],
    }


def _write(tmp_path: Path, content: dict[str, Any], name: str = "site.json") -> Path:
    images = tmp_path / "img"
    images.mkdir(exist_ok=True)
    for picture in ("design", "nexus", "nexus-1", "nexus-2", "nexus-3", "ada"):
        target = images / f"{picture}.png"
        if not target.exists():
            target.write_bytes(PNG)
    path = tmp_path / name
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def _counts(report: Any) -> dict[str, tuple[int, int, int]]:
    return {
        label: (counts.created, counts.updated, counts.unchanged)
        for label, counts in report.models.items()
    }


class TestIdempotentLoading:
    def test_a_first_load_creates_and_a_second_changes_nothing(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _site())
        first = load_content(path)
        assert _counts(first) == {
            "contentapp.Member": (1, 0, 0),
            "contentapp.Service": (2, 0, 0),
            "contentapp.Category": (1, 0, 0),
            "contentapp.Project": (2, 0, 0),
            "contentapp.ProjectImage": (3, 0, 0),
            "contentapp.Slide": (2, 0, 0),
        }
        assert first.changed and first.models["contentapp.Project"].files == 1
        pks = sorted(str(pk) for pk in Project.objects.values_list("pk", flat=True))

        second = load_content(path)
        assert not second.changed
        assert {label: c[2] for label, c in _counts(second).items()} == {
            "contentapp.Member": 1,
            "contentapp.Service": 2,
            "contentapp.Category": 1,
            "contentapp.Project": 2,
            "contentapp.ProjectImage": 3,
            "contentapp.Slide": 2,
        }
        assert "Nothing changed." in second.render()
        assert sorted(str(pk) for pk in Project.objects.values_list("pk", flat=True)) == pks
        assert Project.objects.count() == 2 and ProjectImage.objects.count() == 3

    def test_a_changed_field_updates_the_row_in_place(self, tmp_path: Path) -> None:
        site = _site()
        load_content(_write(tmp_path, site))
        before = Project.objects.get(slug="nexus")
        site["contentapp.Project"][0]["title"] = "Nexus Tower"
        report = load_content(_write(tmp_path, site))
        assert _counts(report)["contentapp.Project"] == (0, 1, 1)
        after = Project.objects.get(slug="nexus")
        assert after.pk == before.pk and after.title == "Nexus Tower"
        assert re.search(r"contentapp.Project +0 created, 1 updated, 1 unchanged", report.render())

    def test_an_explicit_empty_value_is_written(self, tmp_path: Path) -> None:
        site = _site()
        load_content(_write(tmp_path, site))
        site["contentapp.Project"][0]["category"] = None
        load_content(_write(tmp_path, site))
        assert Project.objects.get(slug="nexus").category is None


class TestRelations:
    def test_foreign_keys_and_many_to_many_by_natural_key(self, tmp_path: Path) -> None:
        load_content(_write(tmp_path, _site()))
        nexus = Project.objects.get(slug="nexus")
        assert nexus.category == Category.objects.get(slug="homes")
        assert {s.slug for s in nexus.services.all()} == {"design"}
        assert {s.slug for s in Category.objects.get().key_services.all()} == {"design", "build"}
        # Member.projects names projects that come later in the file.
        ada = Member.objects.get(name="Ada")
        assert {p.slug for p in ada.projects.all()} == {"nexus", "hillside"}

    def test_a_changed_many_to_many_updates_the_row(self, tmp_path: Path) -> None:
        site = _site()
        load_content(_write(tmp_path, site))
        site["contentapp.Project"][0]["services"] = ["design", "build"]
        report = load_content(_write(tmp_path, site))
        assert _counts(report)["contentapp.Project"] == (0, 1, 1)
        nexus = Project.objects.get(slug="nexus")
        assert {s.slug for s in nexus.services.all()} == {"design", "build"}

    def test_a_composite_key_with_a_null_foreign_key(self, tmp_path: Path) -> None:
        site = _site()
        load_content(_write(tmp_path, site))
        site["contentapp.Slide"][0]["heading"] = "Hello"
        report = load_content(_write(tmp_path, site))
        assert _counts(report)["contentapp.Slide"] == (0, 1, 1)
        assert Slide.objects.count() == 2
        assert Slide.objects.get(placement="home", service=None).heading == "Hello"
        assert Slide.objects.get(placement="service").service.slug == "design"

    def test_a_declared_natural_key_matches_rows(self, tmp_path: Path) -> None:
        site = _site()
        load_content(_write(tmp_path, site))
        site["contentapp.Member"][0]["role"] = "Principal"
        report = load_content(_write(tmp_path, site))
        assert _counts(report)["contentapp.Member"] == (0, 1, 0)
        assert list(Member.objects.values_list("name", "role")) == [("Ada", "Principal")]

    def test_a_missing_target_names_the_row_and_field(self, tmp_path: Path) -> None:
        site = _site()
        site["contentapp.Project"][0]["category"] = "offices"
        with pytest.raises(LoadError) as caught:
            load_content(_write(tmp_path, site))
        assert caught.value.code == "E805"
        assert "contentapp.Project (slug='nexus'): category: no category with slug or id " in (
            caught.value.message
        )
        assert "'offices'." in caught.value.message and "visible" not in caught.value.message


class TestFiles:
    def test_a_file_is_uploaded_once_then_again_with_refresh_files(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _site())
        load_content(path)
        nexus = Project.objects.get(slug="nexus")
        first_name = nexus.image.name
        assert first_name.startswith("projects/nexus") and nexus.image.read() == PNG
        assert Service.objects.get(slug="build").image.name == ""  # "" leaves it alone

        (tmp_path / "img" / "nexus.png").write_bytes(PNG + b"changed")
        again = load_content(path)
        assert not again.changed and again.models["contentapp.Project"].files == 0
        assert Project.objects.get(slug="nexus").image.name == first_name

        refreshed = load_content(path, refresh_files=True)
        assert refreshed.models["contentapp.Project"].files == 1
        assert refreshed.models["contentapp.ProjectImage"].files == 3
        image = Project.objects.get(slug="nexus").image
        image.open("rb")
        assert image.read() == PNG + b"changed"

    def test_a_file_the_api_would_refuse_is_refused(self, tmp_path: Path, settings: Any) -> None:
        path = _write(tmp_path, _site())
        (tmp_path / "img" / "ada.png").write_bytes(b"not an image")
        with pytest.raises(LoadError) as caught:
            load_content(path)
        assert "contentapp.Member (name='Ada'): photo: ada.png: Upload a valid image." in (
            caught.value.message
        )
        assert not Member.objects.exists()
        assert not list(Path(settings.MEDIA_ROOT).rglob("*.png"))  # nothing reached storage

    def test_a_required_file_must_be_given(self, tmp_path: Path) -> None:
        site = _site()
        del site["contentapp.Project"][0]["gallery"][1]["image"]
        with pytest.raises(LoadError) as caught:
            load_content(_write(tmp_path, site))
        assert (
            "contentapp.ProjectImage (slug='nexus' > position=2): image: this file is required. "
            "Give its path, relative to site.json."
        ) in caught.value.message

        # Once the row has its file, a later run may leave the path out.
        load_content(_write(tmp_path, _site()))
        report = load_content(_write(tmp_path, site))
        assert not report.changed

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        site = _site()
        site["contentapp.Member"][0]["photo"] = "img/nobody.png"
        with pytest.raises(LoadError, match=r"no such file 'img/nobody.png' \(paths are relative"):
            load_content(_write(tmp_path, site))
        assert not Service.objects.exists()


class TestChildren:
    def test_children_are_matched_by_parent_and_position(self, tmp_path: Path) -> None:
        site = _site()
        load_content(_write(tmp_path, site))
        site["contentapp.Project"][0]["gallery"][2]["alt"] = "Floor plan"
        report = load_content(_write(tmp_path, site))
        assert _counts(report)["contentapp.ProjectImage"] == (0, 1, 2)
        gallery = Project.objects.get(slug="nexus").gallery.order_by("position")
        assert [(g.position, g.alt) for g in gallery] == [
            (1, "Street"),
            (2, "Garden"),
            (3, "Floor plan"),
        ]

    def test_prune_removes_children_the_list_does_not_name(self, tmp_path: Path) -> None:
        site = _site()
        load_content(_write(tmp_path, site))
        site["contentapp.Project"][0]["gallery"] = site["contentapp.Project"][0]["gallery"][:1]
        kept = load_content(_write(tmp_path, site))
        assert kept.models["contentapp.ProjectImage"].pruned == 0
        assert ProjectImage.objects.count() == 3

        pruned = load_content(_write(tmp_path, site), prune=True)
        assert pruned.models["contentapp.ProjectImage"].pruned == 2 and pruned.changed
        assert list(ProjectImage.objects.values_list("position", flat=True)) == [1]
        assert "2 pruned" in pruned.render()

        # Listing them again restores the soft-deleted rows instead of failing on the constraint.
        restored = load_content(_write(tmp_path, _site()))
        assert _counts(restored)["contentapp.ProjectImage"] == (0, 2, 1)
        assert ProjectImage.objects.count() == 3

    def test_a_row_without_its_list_keeps_its_children(self, tmp_path: Path) -> None:
        site = _site()
        load_content(_write(tmp_path, site))
        del site["contentapp.Project"][0]["gallery"]
        report = load_content(_write(tmp_path, site), prune=True)
        assert not report.changed and ProjectImage.objects.count() == 3


class TestValidationAndRollback:
    def test_an_invalid_row_rolls_the_whole_load_back(self, tmp_path: Path) -> None:
        site = _site()
        site["contentapp.Project"][1]["year"] = 1800
        path = _write(tmp_path, site)
        with pytest.raises(LoadError) as caught:
            load_content(path)
        error = caught.value
        assert error.code == "E805"
        assert str(path) in error.message and "nothing was loaded" in error.message
        assert "contentapp.Project (slug='hillside'): year: year must be 1900 or later." in (
            error.message
        )
        assert [p.to_dict() for p in error.problems] == [
            {
                "model": "contentapp.Project",
                "row": "slug='hillside'",
                "field": "year",
                "message": "year must be 1900 or later.",
            }
        ]
        assert not Service.objects.exists() and not Project.objects.exists()
        assert not ChangeBatch.objects.filter(kind="load").exists()

    def test_unknown_and_read_only_names_are_refused(self, tmp_path: Path) -> None:
        site = _site()
        site["contentapp.Member"][0]["nickname"] = "A"
        site["contentapp.Member"][0]["created_at"] = "2026-01-01T00:00:00Z"
        with pytest.raises(LoadError) as caught:
            load_content(_write(tmp_path, site))
        message = caught.value.message
        assert "contentapp.Member (name='Ada'): nickname: not a field of Member. Fields:" in message
        assert "contentapp.Member (name='Ada'): created_at: cannot be set from a content file" in (
            message
        )

    def test_a_row_without_its_key_is_refused(self, tmp_path: Path) -> None:
        site = _site()
        del site["contentapp.Slide"][0]["position"]
        with pytest.raises(LoadError, match=r"contentapp.Slide \(#1\): position: every slide row"):
            load_content(_write(tmp_path, site))

    def test_the_file_itself_is_checked_first(self, tmp_path: Path) -> None:
        with pytest.raises(LoadError, match="no such file") as caught:
            load_content(tmp_path / "missing.json")
        assert caught.value.code == "E804"
        bad = tmp_path / "bad.json"
        bad.write_text("{", encoding="utf-8")
        with pytest.raises(LoadError, match="not valid JSON at line 1"):
            load_content(bad)
        with pytest.raises(LoadError, match="'nope.Thing' is not an installed model"):
            load_content(_write(tmp_path, {"nope.Thing": []}))
        with pytest.raises(LoadError, match="must hold a list of rows"):
            load_content(_write(tmp_path, {"contentapp.Member": {"name": "Ada"}}))

    def test_yaml_loads_like_json(self, tmp_path: Path) -> None:
        pytest.importorskip("yaml")
        path = tmp_path / "team.yaml"
        path.write_text("contentapp.Member:\n  - name: Ada\n    role: Founder\n", encoding="utf-8")
        report = load_content(path)
        assert _counts(report) == {"contentapp.Member": (1, 0, 0)}


class TestDryRunAndAttribution:
    def test_a_dry_run_reports_and_writes_nothing(self, tmp_path: Path, settings: Any) -> None:
        report = load_content(_write(tmp_path, _site()), dry_run=True)
        assert _counts(report)["contentapp.Project"] == (2, 0, 0)
        assert report.models["contentapp.Member"].files == 1
        assert report.render().startswith("Dry run of ")
        assert not Project.objects.exists() and not ProjectImage.objects.exists()
        assert not list(Path(settings.MEDIA_ROOT).glob("team/ada*"))

    def test_writes_are_attributed_to_the_actor_and_batched(
        self, tmp_path: Path, django_user_model: Any
    ) -> None:
        editor = django_user_model.objects.create_user(email="editor@example.com", password="x")
        load_content(_write(tmp_path, _site()), actor=editor)
        nexus = Project.objects.get(slug="nexus")
        assert nexus.created_by == editor and nexus.updated_by == editor
        batch = ChangeBatch.objects.get(kind="load")
        assert batch.actor_id == editor.pk and batch.label == "site.json"

    def test_a_subclass_can_put_a_check_back(self, tmp_path: Path) -> None:
        class NoCreates(ContentImporter):
            def may_create(self) -> bool:
                return False

        with pytest.raises(LoadError, match="you may not add service rows"):
            load_content(_write(tmp_path, _site()), importer_class=NoCreates)


class TestRoutedModels:
    def test_a_routed_model_loads_without_its_gate_and_stamps_the_owner(
        self, tmp_path: Path, django_user_model: Any
    ) -> None:
        nobody = django_user_model.objects.create_user(email="nobody@example.com", password="x")
        content: dict[str, list[dict[str, Any]]] = {
            "testapp.Venue": [{"name": "Arena", "city": "Berlin"}],
            "testapp.Tag": [{"name": "jazz"}],
            "testapp.Event": [
                {
                    "id": "8b0c8c1e-4a8e-4f53-9a38-0c3f0a0b6a11",
                    "title": "Gig",
                    "starts_at": "2026-02-01T10:00:00Z",
                    "venue": "Arena",
                    "tags": ["jazz"],
                }
            ],
        }
        report = load_content(_write(tmp_path, content), actor=nobody)
        assert _counts(report)["testapp.Event"] == (1, 0, 0)
        event = Event.objects.get()
        assert event.organizer == nobody and event.venue.name == "Arena"
        assert [tag.name for tag in event.tags.all()] == ["jazz"]
        assert not load_content(_write(tmp_path, content), actor=nobody).changed

        content["testapp.Event"][0]["status"] = "published"
        with pytest.raises(LoadError, match="status: cannot be set from a content file"):
            load_content(_write(tmp_path, content))


class TestCommand:
    def test_the_management_command(self, tmp_path: Path, django_user_model: Any) -> None:
        path = _write(tmp_path, _site())
        out = StringIO()
        call_command("karni_load", str(path), "--dry-run", stdout=out)
        assert "Dry run of" in out.getvalue() and not Project.objects.exists()

        django_user_model.objects.create_user(email="editor@example.com", password="x")
        out = StringIO()
        call_command("karni_load", str(path), "--as", "editor@example.com", "--json", stdout=out)
        data = json.loads(out.getvalue())
        assert data["changed"] and data["models"]["contentapp.Project"]["created"] == 2

        out = StringIO()
        call_command("karni_load", str(path), stdout=out)
        assert out.getvalue().strip().endswith("Nothing changed.")

        with pytest.raises(CommandError, match="E804: No user 'ghost@example.com'"):
            call_command("karni_load", str(path), "--as", "ghost@example.com")
        with pytest.raises(CommandError, match="E804: .*no such file"):
            call_command("karni_load", str(tmp_path / "nope.json"))

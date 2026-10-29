"""Uploaded images: WebP copies next to the original, the upload cap, {% image %}, the fallback."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from django.core.files.storage import InMemoryStorage, default_storage
from django.template import RequestContext, Template
from django.test import RequestFactory
from pytest_django import Settings

from karni_site import imagesize, renditions
from karni_site.models import Block
from tests.seo_helpers import jpeg, seo_site, upload  # noqa: F401
from tests.testapp.models import Project

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("seo_site")]

WIDTHS = [320, 480, 640, 800, 960, 1280, 1600, 1920]


def render(source: str, **context: Any) -> str:
    template = Template("{% load karni_site %}" + source)
    return template.render(RequestContext(RequestFactory().get("/"), context))


def picture(name: str) -> Any:
    from PIL import Image

    with default_storage.open(name, "rb") as handle:
        image = Image.open(BytesIO(handle.read()))
        image.load()
    return image


@pytest.fixture
def project(django_capture_on_commit_callbacks: Any) -> Project:
    with django_capture_on_commit_callbacks(execute=True):
        return Project.objects.create(
            title="Wedding cake", slug="wedding", photo=upload("cake.jpg", 2000, 1000)
        )


def test_an_upload_gets_webp_copies_next_to_it(project: Project) -> None:
    name = project.photo.name
    # Each width below the image's, and the whole picture in WebP.
    for width in [*WIDTHS, 2000]:
        copy = picture(renditions.rendition_name(name, width))
        assert (copy.format, copy.size) == ("WEBP", (width, width // 2))
    assert not default_storage.exists(renditions.rendition_name(name, 2560))
    with default_storage.open(renditions.manifest_name(name)) as handle:
        manifest = json.loads(handle.read())
    assert manifest["width"] == 2000 and manifest["height"] == 1000
    assert manifest["widths"] == [*WIDTHS, 2000]
    assert renditions.rendition_name(name, 640) == f"{name}.640w.webp"


def test_the_upload_cap_scales_the_original_down(
    settings: Settings, django_capture_on_commit_callbacks: Any
) -> None:
    settings.KARNI_SITE_IMAGE_MAX_SIZE = 1000
    with django_capture_on_commit_callbacks(execute=True):
        found = Project.objects.create(title="Big", slug="big", photo=upload("big.jpg", 3000, 1500))
    original = picture(found.photo.name)
    assert (original.format, original.size) == ("JPEG", (1000, 500))
    manifest = renditions.read_manifest(found.photo.name, default_storage)
    assert manifest is not None and manifest.widths == (320, 480, 640, 800, 960, 1000)


def test_the_widths_and_quality_are_settings(
    settings: Settings, django_capture_on_commit_callbacks: Any
) -> None:
    settings.KARNI_SITE_IMAGE_WIDTHS = [500]
    settings.KARNI_SITE_IMAGE_QUALITY = 30
    with django_capture_on_commit_callbacks(execute=True):
        found = Project.objects.create(title="Q", slug="q", photo=upload("q.jpg", 800, 400))
    manifest = renditions.read_manifest(found.photo.name, default_storage)
    assert manifest is not None and manifest.widths == (500, 800)


def test_image_writes_srcset_sizes_width_height_and_lazy_loading(project: Project) -> None:
    html = render(
        '{% image project.photo width=400 alt=project.title class="card" data_index=2 %}',
        project=project,
    )
    name = project.photo.name
    srcset = ", ".join(f"/media/{name}.{w}w.webp {w}w" for w in [*WIDTHS, 2000])
    assert html == (
        f'<img src="/media/{name}.480w.webp" srcset="{srcset}" '
        'sizes="auto, (max-width: 400px) 100vw, 400px" width="400" height="200" '
        'alt="Wedding cake" loading="lazy" decoding="async" data-karni-image class="card" '
        'data-index="2">'
    )


def test_an_image_at_the_top_of_a_page_loads_at_once(project: Project) -> None:
    html = render('{% image project.photo alt="" fetchpriority="high" %}', project=project)
    assert 'sizes="(max-width: 2000px) 100vw, 2000px"' in html
    assert 'width="2000" height="1000"' in html and 'alt=""' in html
    assert "loading=" not in html and 'fetchpriority="high"' in html
    html = render('{% image project.photo alt="" loading="eager" %}', project=project)
    assert 'loading="eager"' in html and "auto," not in html


def test_an_empty_field_renders_nothing() -> None:
    assert render('{% image project.photo alt="x" %}', project=Project(title="none")) == ""


def test_alt_is_required() -> None:
    from django.template import TemplateSyntaxError

    with pytest.raises(TemplateSyntaxError, match='SITE019: {% image %} needs alt="..."'):
        Template("{% load karni_site %}{% image project.photo width=400 %}")
    with pytest.raises(TemplateSyntaxError, match="SITE019"):
        Template('{% load karni_site %}{% image project.photo alt="x" 400 %}')


def test_a_missing_rendition_falls_back_to_the_original(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.KARNI_SITE_QUEUE_RENDITIONS = False
    found = Project.objects.create(title="Late", slug="late", photo=upload("late.jpg", 1200, 600))
    assert not default_storage.exists(renditions.manifest_name(found.photo.name))
    html = render('{% image found.photo width=300 alt="Late" %}', found=found)
    # The original, sized from its own file, and no srcset until the copies exist.
    assert f'src="/media/{found.photo.name}"' in html
    assert 'width="300" height="150"' in html and "srcset" not in html


def test_a_page_queues_the_copies_it_misses_once(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Any
) -> None:
    settings.KARNI_SITE_QUEUE_RENDITIONS = False
    found = Project.objects.create(title="Old", slug="old", photo=upload("old.jpg", 1000, 500))
    settings.KARNI_SITE_QUEUE_RENDITIONS = True
    queued: list[tuple[Any, ...]] = []
    from karni_site import tasks

    monkeypatch.setattr(
        tasks.make_renditions, "apply_async", lambda args, **kwargs: queued.append(args)
    )
    with django_capture_on_commit_callbacks(execute=True):
        render('{% image found.photo alt="" %}', found=found)
        renditions.forget(found.photo.name)
        render('{% image found.photo alt="" %}', found=found)
    assert queued == [(found.photo.name, "testapp.Project.photo", False)]


def test_the_copies_go_through_the_projects_storage(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = InMemoryStorage(base_url="https://cdn.example.com/")
    storage.save("shop/front.jpg", BytesIO(jpeg(1400, 700)))
    monkeypatch.setattr(renditions, "storage_for", lambda ref: storage)
    manifest = renditions.make("shop/front.jpg", "")
    assert manifest is not None and manifest.widths == (320, 480, 640, 800, 960, 1280, 1400)
    assert storage.exists("shop/front.jpg.1400w.webp")
    source = renditions.Source(
        "shop/front.jpg", storage, "", "https://cdn.example.com/shop/front.jpg"
    )
    found = renditions.attributes(source, width=640)
    assert found["src"] == "https://cdn.example.com/shop/front.jpg.640w.webp"
    assert found["srcset"].endswith("https://cdn.example.com/shop/front.jpg.1400w.webp 1400w")
    # A second run finds the copies current and makes nothing.
    settings.KARNI_SITE_RENDITIONER = "tests.test_renditions.record_call"
    RECORD.clear()
    assert renditions.make("shop/front.jpg", "") == manifest
    assert RECORD == []
    assert renditions.make("shop/front.jpg", "", force=True) is None
    assert RECORD == ["shop/front.jpg"]


RECORD: list[str] = []


def record_call(name: str, storage: Any) -> None:
    RECORD.append(name)


def test_without_pillow_the_image_keeps_its_size(
    monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Any
) -> None:
    monkeypatch.setattr(renditions, "_pillow", lambda: None)
    with django_capture_on_commit_callbacks(execute=True):
        found = Project.objects.create(title="P", slug="p", photo=upload("p.jpg", 900, 300))
    manifest = renditions.read_manifest(found.photo.name, default_storage)
    assert manifest == renditions.Manifest(900, 300, (), found.photo.size)
    assert not default_storage.exists(renditions.rendition_name(found.photo.name, 320))
    html = render('{% image found.photo alt="" %}', found=found)
    assert 'width="900" height="300"' in html and "srcset" not in html


def test_a_storage_that_fails_never_breaks_the_page(
    monkeypatch: pytest.MonkeyPatch, project: Project
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("the bucket is gone")

    renditions.forget(project.photo.name)
    from django.core.files.storage import FileSystemStorage

    monkeypatch.setattr(FileSystemStorage, "open", broken)
    monkeypatch.setattr(renditions, "queue", lambda *args, **kwargs: None)
    html = render('{% image project.photo alt="x" %}', project=project)
    assert html.startswith(f'<img src="/media/{project.photo.name}" alt="x"')


def test_an_uploaded_block_image_gets_its_copies(
    django_capture_on_commit_callbacks: Any,
) -> None:
    source = (
        '{% editable_image "home.hero" %}<img class="hero" src="/static/hero.jpg" width="600" '
        'height="300" alt="The oven" loading="lazy">{% endeditable_image %}'
    )
    render(source)
    block = Block.objects.get(key="home.hero")
    with django_capture_on_commit_callbacks(execute=True):
        block.image = upload("oven.jpg", 1600, 1200)
        block.save()
    html = render(source)
    name = block.image.name
    assert f'src="/media/{name}"' in html and 'class="hero"' in html
    # The designer's width stays, the height follows the new picture.
    assert 'width="600" height="450"' in html
    assert f"/media/{name}.320w.webp 320w" in html and f"/media/{name}.1600w.webp 1600w" in html
    assert 'sizes="auto, (max-width: 600px) 100vw, 600px"' in html


def test_derived_files_are_never_copied_again() -> None:
    assert renditions.is_derived("a/b.jpg.640w.webp")
    assert renditions.is_derived("a/b.jpg.renditions.json")
    assert not renditions.is_derived("a/b.jpg")
    assert renditions.make("a/b.jpg.640w.webp") is None


# reading sizes without Pillow


def test_sizes_are_read_from_the_first_bytes(tmp_path: Path) -> None:
    from PIL import Image

    for fmt in ("PNG", "GIF", "WEBP", "JPEG"):
        buffer = BytesIO()
        Image.new("RGB", (321, 123)).save(buffer, format=fmt)
        assert imagesize.image_size(buffer.getvalue()) == (321, 123), fmt
    lossless = BytesIO()
    Image.new("RGBA", (77, 55)).save(lossless, format="WEBP", lossless=True)
    assert imagesize.image_size(lossless.getvalue()) == (77, 55)
    assert imagesize.image_size(b'<svg width="40px" height="20" viewBox="0 0 4 2">') == (40, 20)
    assert imagesize.image_size(b'<svg viewBox="0 0 4 2">') is None
    assert imagesize.image_size(b"not an image") is None


def test_a_photo_taken_on_its_side_reports_upright() -> None:
    from PIL import Image

    image = Image.new("RGB", (400, 300))
    exif = image.getexif()
    exif[0x0112] = 6  # rotate 90 degrees
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    assert imagesize.image_size(buffer.getvalue()) == (300, 400)

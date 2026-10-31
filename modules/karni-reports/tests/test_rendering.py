"""The renderers: one real WeasyPrint render, what it may fetch, and loading the setting."""

from __future__ import annotations

import builtins
from typing import Any

import pytest
from django.conf import LazySettings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from karni.exceptions import KarniImportError, KarniImproperlyConfigured

from karni_reports import get_report
from karni_reports.rendering import (
    BASE_URL,
    FakeRenderer,
    Renderer,
    WeasyPrintRenderer,
    get_renderer,
)
from tests.testapp.models import Product


def _weasyprint() -> Any:
    """WeasyPrint, or a skip naming what is missing (it needs Pango, a system library)."""
    try:
        import weasyprint
    except (ImportError, OSError) as exc:
        pytest.skip(
            f"WeasyPrint cannot load here ({exc}): install Pango (apt-get install "
            "libpango-1.0-0 libpangoft2-1.0-0, or brew install pango). CI installs it."
        )
    return weasyprint


@pytest.mark.django_db
def test_weasyprint_renders_a_real_pdf(product: Product) -> None:
    _weasyprint()
    report = get_report("product-sheet")
    html = report.render_html(product, report.get_context(product))
    pdf = WeasyPrintRenderer().render(html)
    assert pdf.startswith(b"%PDF-") and len(pdf) > 1000
    assert b"%%EOF" in pdf[-1024:]


def test_weasyprint_reads_static_and_media_files_and_never_the_network() -> None:
    weasyprint = _weasyprint()
    renderer = WeasyPrintRenderer()
    css = renderer.local_file(f"{BASE_URL}static/products/print.css")
    assert css == (b"h1 { color: #222; }\n", "text/css")
    name = default_storage.save("logos/mark.svg", ContentFile(b"<svg/>"))
    assert renderer.local_file(f"{BASE_URL}media/{name}") == (b"<svg/>", "image/svg+xml")
    assert renderer.local_file("http://169.254.169.254/latest/meta-data/") is None
    assert renderer.local_file(f"{BASE_URL}static/../settings.py") is None
    assert renderer.local_file(f"{BASE_URL}static/products/missing.css") is None
    html = (
        '<link rel="stylesheet" href="/static/products/print.css">'
        '<img src="http://example.com/tracker.png"><h1>Hi</h1>'
    )
    pdf = weasyprint.HTML(string=html, base_url=BASE_URL, url_fetcher=renderer.fetcher())
    assert pdf.write_pdf().startswith(b"%PDF-")


def test_the_renderer_setting_takes_shortcuts_and_dotted_paths(settings: LazySettings) -> None:
    assert isinstance(get_renderer(), FakeRenderer)
    settings.KARNI_REPORTS_RENDERER = "weasyprint"
    assert isinstance(get_renderer(), WeasyPrintRenderer)
    settings.KARNI_REPORTS_RENDERER = "karni_reports.rendering.FakeRenderer"
    assert isinstance(get_renderer(), FakeRenderer)
    for wrong in ("no.such.Renderer", "karni_reports.conf.get"):
        settings.KARNI_REPORTS_RENDERER = wrong
        with pytest.raises(KarniImproperlyConfigured) as caught:
            get_renderer()
        assert caught.value.code == "REPORT005"


def test_a_missing_system_library_names_the_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def without_pango(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "weasyprint":
            raise OSError("cannot load library 'libpango-1.0-0'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pango)
    with pytest.raises(KarniImportError) as caught:
        WeasyPrintRenderer().render("<p>x</p>")
    assert caught.value.code == "REPORT006" and "libpango-1.0-0" in str(caught.value)


def test_the_fake_renderer_is_deterministic_and_records_the_html() -> None:
    first = FakeRenderer().render("<p>a</p>")
    assert first == FakeRenderer().render("<p>a</p>") != FakeRenderer().render("<p>b</p>")
    assert FakeRenderer.rendered == ["<p>a</p>", "<p>a</p>", "<p>b</p>"]
    assert Renderer().identity() == "karni_reports.rendering.Renderer"

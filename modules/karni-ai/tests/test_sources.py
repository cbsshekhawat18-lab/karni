"""The source: text limits, an HTML page's visible text, a PDF's text layer and its refusals."""

from __future__ import annotations

import io
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from karni_ai.exceptions import ExtractionRefused
from karni_ai.services.fetch import Fetched, Fetcher
from karni_ai.sources import pdf_text, read_source, visible_text
from tests.pdfs import make_pdf


def refused(**source: Any) -> ExtractionRefused:
    with pytest.raises(ExtractionRefused) as exc:
        read_source(**source)
    return exc.value


def test_text_is_kept_as_given() -> None:
    source = read_source(text="  Name: Hose\n")
    assert (source.kind, source.label, source.text) == ("text", "text", "Name: Hose")


def test_visible_text_leaves_out_scripts_styles_and_head() -> None:
    html = (
        "<html><head><title>T</title><style>p{}</style></head><body>"
        "<h1>Catalog</h1><script>secret()</script><table><tr><td>Hose</td><td>9.50</td></tr>"
        "</table><p>Tom &amp; Jerry&nbsp;tools</p><template>hidden</template></body></html>"
    )
    assert visible_text(html).splitlines() == ["Catalog", "Hose 9.50", "Tom & Jerry\xa0tools"]


def test_a_pdf_upload_is_read() -> None:
    upload = SimpleUploadedFile("list.pdf", make_pdf(["Name: Hose", "Price: 9.50"]))
    source = read_source(file=upload)
    assert source.kind == "pdf" and source.label == "list.pdf"
    assert source.text == "Name: Hose\nPrice: 9.50"


def test_not_a_pdf() -> None:
    upload = SimpleUploadedFile("list.pdf", b"Name: Hose")
    assert refused(file=upload).message == "The file is not a PDF."


def test_a_broken_pdf() -> None:
    assert refused(file=SimpleUploadedFile("x.pdf", b"%PDF-1.4\ngarbage")).code == "AI010"


def test_a_pdf_without_text_is_refused() -> None:
    error = refused(file=SimpleUploadedFile("scan.pdf", make_pdf([])))
    assert "no text layer" in error.message


def test_a_locked_pdf_is_refused() -> None:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(make_pdf(["Name: Hose"]))).pages:
        writer.add_page(page)
    writer.encrypt(user_password="secret", owner_password="owner")
    buffer = io.BytesIO()
    writer.write(buffer)
    error = refused(file=SimpleUploadedFile("locked.pdf", buffer.getvalue()))
    assert "password" in error.message


def test_too_many_pages() -> None:
    with override_settings(KARNI_AI_MAX_PDF_PAGES=2):
        error = refused(file=SimpleUploadedFile("long.pdf", make_pdf(["Name: A"], pages=3)))
    assert "3 pages" in error.message and "KARNI_AI_MAX_PDF_PAGES" in error.message


def test_an_upload_over_the_limit() -> None:
    with override_settings(KARNI_AI_MAX_UPLOAD_BYTES=100):
        error = refused(file=SimpleUploadedFile("big.pdf", make_pdf(["Name: Hose"] * 20)))
    assert "KARNI_AI_MAX_UPLOAD_BYTES" in error.message


def test_a_fetched_pdf_and_plain_text(monkeypatch: Any) -> None:
    pages = {
        "https://shop.example.com/list.pdf": Fetched(
            "https://shop.example.com/list.pdf", "application/pdf", None, make_pdf(["Name: Rake"])
        ),
        "https://shop.example.com/list.txt": Fetched(
            "https://shop.example.com/list.txt", "text/plain", "utf-8", b"Name: Hoe\n\nName: Fork"
        ),
        "https://shop.example.com/image.png": Fetched(
            "https://shop.example.com/image.png", "image/png", None, b"\x89PNG"
        ),
    }
    monkeypatch.setattr(Fetcher, "fetch", lambda self, url: pages[url])
    assert read_source(url="https://shop.example.com/list.pdf").text == "Name: Rake"
    assert read_source(url="https://shop.example.com/list.txt").text == "Name: Hoe\n\nName: Fork"
    error = refused(url="https://shop.example.com/image.png")
    assert error.code == "AI012" and "image/png" in error.message


def test_the_fetcher_setting_must_name_a_fetcher() -> None:
    from karni.exceptions import KarniImproperlyConfigured

    for value in ("karni_ai.sources.Source", "no.such.Fetcher"):
        with (
            override_settings(KARNI_AI_FETCHER=value),
            pytest.raises(KarniImproperlyConfigured) as exc,
        ):
            read_source(url="https://shop.example.com/")
        assert exc.value.code == "AI016"


def test_pdf_text_reads_every_page() -> None:
    assert pdf_text(make_pdf(["Name: A"], pages=2)) == "Name: A"

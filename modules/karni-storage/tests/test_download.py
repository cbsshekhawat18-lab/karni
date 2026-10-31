"""GET <resource>/<id>/files/<field>/: the row's viewset first, then the file."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from tests.testapp.models import Product

pytestmark = pytest.mark.django_db


def _path(product: Product, field: str = "manual") -> str:
    return f"/api/products/{product.pk}/files/{field}/"


@pytest.fixture
def product(make_product: Any) -> Product:
    product: Product = make_product()
    product.manual.save("guide.txt", ContentFile(b"how to use the lamp"), save=True)
    return product


def _body(response: Any) -> bytes:
    return b"".join(response.streaming_content)


def test_the_api_gives_the_download_path_never_a_storage_url(
    owner_api: APIClient, product: Product
) -> None:
    data = owner_api.get(f"/api/products/{product.pk}/").json()
    assert data["manual"] == f"http://testserver{_path(product)}"
    assert data["photo"] is None
    assert "invoice" not in data  # field_roles hides it from the owner


def test_the_owner_gets_the_file_streamed_from_local_storage(
    owner_api: APIClient, product: Product
) -> None:
    response = owner_api.get(_path(product))
    assert response.status_code == 200
    assert _body(response) == b"how to use the lamp"
    assert response["Content-Type"].startswith("text/plain")
    assert response["Content-Disposition"].startswith("inline")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "private, max-age=300"


def test_download_asks_for_an_attachment(owner_api: APIClient, product: Product) -> None:
    response = owner_api.get(_path(product), {"download": "1"})
    assert response["Content-Disposition"].startswith("attachment")
    assert "guide" in response["Content-Disposition"]


def test_another_users_row_is_a_404(other_api: APIClient, product: Product) -> None:
    response = other_api.get(_path(product))
    assert response.status_code == 404
    assert b"how to use" not in response.content


def test_an_anonymous_caller_is_refused(api: APIClient, product: Product) -> None:
    response = api.get(_path(product))
    assert response.status_code in (401, 403)


def test_a_soft_deleted_row_is_a_404(owner_api: APIClient, product: Product) -> None:
    product.delete()
    assert Product.objects.without("soft_delete", reason="the test").filter(pk=product.pk).exists()
    assert owner_api.get(_path(product)).status_code == 404


def test_a_missing_row_is_a_404(owner_api: APIClient, product: Product) -> None:
    pk = product.pk
    product.hard_delete()
    assert owner_api.get(f"/api/products/{pk}/files/manual/").status_code == 404


def test_an_empty_field_and_an_unknown_field(owner_api: APIClient, product: Product) -> None:
    empty = owner_api.get(_path(product, "photo"))
    assert empty.status_code == 404 and "STORE018" in str(empty.json())
    unknown = owner_api.get(_path(product, "name"))
    assert unknown.status_code == 404 and "STORE010" in str(unknown.json())
    resource = owner_api.get(f"/api/gadgets/{product.pk}/files/manual/")
    assert resource.status_code == 404 and "STORE010" in str(resource.json())


def test_a_field_hidden_by_field_roles_is_a_404(
    owner_api: APIClient, product: Product, owner: Any
) -> None:
    product.invoice.save("invoice.txt", ContentFile(b"total"), save=True)
    response = owner_api.get(_path(product, "invoice"))
    assert response.status_code == 404 and "STORE010" in str(response.json())
    owner.is_superuser = True
    owner.save()
    assert owner_api.get(_path(product, "invoice")).status_code == 200


def test_svg_is_never_served_inline(owner_api: APIClient, make_product: Any) -> None:
    product = make_product()
    product.manual.save("drawing.svg", ContentFile(b"<svg/>"), save=True)
    response = owner_api.get(_path(product))
    assert response["Content-Disposition"].startswith("attachment")


def test_a_json_link_on_local_storage_opens_without_a_session(
    owner_api: APIClient, api: APIClient, product: Product
) -> None:
    answer = owner_api.get(_path(product), HTTP_ACCEPT="application/json")
    assert answer.status_code == 200
    data = answer.json()
    assert data["expires_in"] == 300 and data["name"] == product.manual.name.rsplit("/", 1)[-1]
    url = urlsplit(data["url"])
    assert url.path == _path(product) and "sig" in parse_qs(url.query)
    opened = api.get(url.path, parse_qs(url.query))
    assert opened.status_code == 200 and _body(opened) == b"how to use the lamp"


def test_a_tampered_or_stale_link_is_refused(
    owner_api: APIClient, api: APIClient, product: Product
) -> None:
    data = owner_api.get(_path(product), HTTP_ACCEPT="application/json").json()
    query = parse_qs(urlsplit(data["url"]).query)
    signature = query["sig"][0]
    tampered = api.get(_path(product), {"sig": signature[:-2] + "xx"})
    assert tampered.status_code == 403 and "STORE019" in str(tampered.json())
    # Another size than the one signed.
    assert api.get(_path(product), {"sig": signature, "size": "small"}).status_code == 403
    # The file was replaced: the old link opens nothing.
    product.manual.save("guide-2.txt", ContentFile(b"new"), save=True)
    replaced = api.get(_path(product), {"sig": signature})
    assert replaced.status_code == 403 and "STORE019" in str(replaced.json())


def test_an_expired_link_is_refused(
    owner_api: APIClient, api: APIClient, product: Product, settings: Any
) -> None:
    data = owner_api.get(_path(product), HTTP_ACCEPT="application/json").json()
    settings.KARNI_STORAGE_URL_EXPIRY = -1
    response = api.get(urlsplit(data["url"]).path, parse_qs(urlsplit(data["url"]).query))
    assert response.status_code == 403 and "expired" in str(response.json())


def test_on_a_bucket_the_download_redirects_to_a_short_lived_signed_url(
    owner_api: APIClient, make_product: Any, bucket: Any, settings: Any
) -> None:
    settings.KARNI_STORAGE_URL_EXPIRY = 120
    product = make_product(manual="products/manuals/abc/guide.pdf")
    response = owner_api.get(_path(product))
    assert response.status_code == 302
    assert response["Cache-Control"] == "private, no-store"
    url = urlsplit(response["Location"])
    assert url.scheme == "https"
    assert url.netloc == "karni-test-bucket.s3.eu-west-1.amazonaws.com"
    assert url.path == "/protected/products/manuals/abc/guide.pdf"
    query = parse_qs(url.query)
    assert query["X-Amz-Expires"] == ["120"]
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Credential"][0].startswith("AKIAKARNITEST/")
    assert "/eu-west-1/s3/aws4_request" in query["X-Amz-Credential"][0]
    assert query["response-content-disposition"] == ['inline; filename="guide.pdf"']
    assert "X-Amz-Signature" in query


def test_on_a_bucket_other_users_get_no_url(
    other_api: APIClient, make_product: Any, bucket: Any
) -> None:
    product = make_product(manual="products/manuals/abc/guide.pdf")
    response = other_api.get(_path(product))
    assert response.status_code == 404 and "Location" not in response


def test_on_a_bucket_the_json_link_is_the_signed_url(
    owner_api: APIClient, make_product: Any, bucket: Any
) -> None:
    product = make_product(manual="products/manuals/abc/notes.html")
    data = owner_api.get(_path(product), HTTP_ACCEPT="application/json").json()
    url = urlsplit(data["url"])
    assert url.netloc == "karni-test-bucket.s3.eu-west-1.amazonaws.com"
    # HTML is never shown inline from the bucket either.
    assert parse_qs(url.query)["response-content-disposition"][0].startswith("attachment")

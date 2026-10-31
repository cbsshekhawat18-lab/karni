from __future__ import annotations

from typing import Any


def test_the_api_gives_the_download_path(owner_api: Any, make_product: Any) -> None:
    from django.core.files.base import ContentFile

    product = make_product()
    product.manual.save("guide.txt", ContentFile(b"hello"), save=True)
    response = owner_api.get(f"/api/products/{product.pk}/")
    assert response.status_code == 200, response.content
    assert response.json()["manual"] == f"http://testserver/api/products/{product.pk}/files/manual/"
    download = owner_api.get(f"/api/products/{product.pk}/files/manual/")
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == b"hello"

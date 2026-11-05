"""The portal's tests: the cache is on (features: api_cache)."""

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _only_the_current_cache_header(settings: Any) -> None:
    settings.KARNI_API_CACHE_LEGACY_HEADER = False

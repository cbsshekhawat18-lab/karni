"""Local ID tokens for the sign-in tests: keys made here, a fake key-set fetcher, no network.

Every key is generated once per test session with ``cryptography``. A token is
minted with :func:`mint` and verified against the key set the fake fetcher
serves (:data:`JWKS`), so the tests exercise the real PyJWT verification with
nothing but local data. ``FETCHES`` counts the fetches per URL.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any, ClassVar

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from karni.accounts.social_token import (
    AppleProvider,
    GoogleProvider,
    IdTokenProvider,
    MicrosoftProvider,
)

GOOGLE_CLIENT = "web-client.apps.example.test"
GOOGLE_IOS_CLIENT = "ios-client.apps.example.test"
MICROSOFT_CLIENT = "6731de76-14a6-49ae-97bc-6eba6914391e"
APPLE_SERVICE = "com.example.web"
APPLE_BUNDLE = "com.example.app"
EC_CLIENT = "ec-client"

ORG_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"
OTHER_TENANT = "11111111-2222-4333-8444-555555555555"
CONSUMERS = MicrosoftProvider.CONSUMERS_TENANT

FETCHER = "tests.accounts.idtokens.fake_fetch"
EC_JWKS_URL = "https://idp.example.test/jwks"


def _rsa() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEYS: dict[str, Any] = {
    "rsa-1": _rsa(),
    "rsa-2": _rsa(),
    "rsa-other": _rsa(),
    "ec-1": ec.generate_private_key(ec.SECP256R1()),
}


def public_jwk(kid: str) -> dict[str, Any]:
    """The public half of ``KEYS[kid]`` as a JWK, the way a provider publishes it."""
    key = KEYS[kid]
    if kid.startswith("ec"):
        jwk = ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
        jwk.update(kid=kid, use="sig", alg="ES256")
    else:
        jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
        jwk.update(kid=kid, use="sig", alg="RS256")
    return dict(jwk)


#: URL -> the JWKS document the fake fetcher answers with.
JWKS: dict[str, dict[str, Any]] = {}
#: URL -> how many times the fake fetcher was called for it.
FETCHES: Counter[str] = Counter()
#: URLs the fake fetcher fails for (a provider that cannot be reached).
UNREACHABLE: set[str] = set()


def serve(url: str, *kids: str) -> None:
    """Make the fake fetcher answer ``url`` with the public keys ``kids``."""
    JWKS[url] = {"keys": [public_jwk(kid) for kid in kids]}


def reset() -> None:
    JWKS.clear()
    FETCHES.clear()
    UNREACHABLE.clear()
    serve(GoogleProvider.jwks_url, "rsa-1")
    serve(MicrosoftProvider.jwks_url, "rsa-1")
    serve(AppleProvider.jwks_url, "rsa-1")
    serve(EC_JWKS_URL, "ec-1")


def fake_fetch(url: str) -> dict[str, Any]:
    """The ``KARNI_SOCIAL_TOKEN_JWKS_FETCHER`` of these tests."""
    FETCHES[url] += 1
    if url in UNREACHABLE:
        raise OSError(f"{url} is unreachable in this test")
    return JWKS[url]


class ExampleEcProvider(IdTokenProvider):
    """A project's own provider (the escape hatch), signing with ES256."""

    jwks_url = EC_JWKS_URL
    issuers = ("https://idp.example.test",)
    algorithms: ClassVar[tuple[str, ...]] = ("ES256",)


def claims_for(provider: str, **overrides: Any) -> dict[str, Any]:
    """Claims a real token of ``provider`` carries, with ``overrides`` applied (None drops one)."""
    now = int(time.time())
    base: dict[str, Any] = {"iat": now, "exp": now + 600, "sub": f"{provider}-subject-1"}
    if provider == "google":
        base.update(
            iss="https://accounts.google.com",
            aud=GOOGLE_CLIENT,
            email="ada@example.com",
            email_verified=True,
            given_name="Ada",
            family_name="Lovelace",
        )
    elif provider == "microsoft":
        base.update(
            iss=f"https://login.microsoftonline.com/{ORG_TENANT}/v2.0",
            aud=MICROSOFT_CLIENT,
            tid=ORG_TENANT,
            oid="00000000-0000-4000-8000-00000000abcd",
            email="grace@contoso.example",
            preferred_username="grace@contoso.example",
            name="Grace Hopper",
            xms_edov=True,
        )
    elif provider == "apple":
        base.update(
            iss="https://appleid.apple.com",
            aud=APPLE_BUNDLE,
            email="x7k2@privaterelay.appleid.com",
            email_verified="true",
            is_private_email="true",
        )
    elif provider == "ecidp":
        base.update(
            iss="https://idp.example.test",
            aud=EC_CLIENT,
            email="ec@example.com",
            email_verified=True,
        )
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def mint(
    provider: str = "google",
    *,
    kid: str = "rsa-1",
    alg: str | None = None,
    key: Any = None,
    headers: dict[str, Any] | None = None,
    **claims: Any,
) -> str:
    """A signed ID token for ``provider`` with :func:`claims_for`'s claims."""
    algorithm = alg or ("ES256" if kid.startswith("ec") else "RS256")
    signing = key if key is not None else KEYS[kid]
    return jwt.encode(
        claims_for(provider, **claims),
        signing,
        algorithm=algorithm,
        headers={"kid": kid, **(headers or {})},
    )


PROVIDERS: dict[str, dict[str, Any]] = {
    "google": {"client_ids": [GOOGLE_CLIENT, GOOGLE_IOS_CLIENT]},
    "microsoft": {"client_ids": [MICROSOFT_CLIENT]},
    "apple": {"client_ids": [APPLE_SERVICE, APPLE_BUNDLE]},
    "ecidp": {"class": "tests.accounts.idtokens.ExampleEcProvider", "client_ids": [EC_CLIENT]},
}

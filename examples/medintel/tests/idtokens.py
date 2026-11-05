"""A local Google ID token and a fake key-set fetcher: the real signature check, no network.

Karni's own tests use the same idea (packages/karni/tests/accounts/idtokens.py).
Set KARNI_SOCIAL_TOKEN_JWKS_FETCHER to ``tests.idtokens.fake_fetch`` to use it.
"""

import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "medintel-test-key"


def fake_fetch(url: str) -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": KID, "use": "sig", "alg": "RS256"}]}


def mint(client_id: str, email: str, **claims: Any) -> str:
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": client_id,
        "sub": f"google-{email}",
        "iat": now,
        "exp": now + 600,
        "email": email,
        "email_verified": True,
        **claims,
    }
    return jwt.encode(payload, KEY, algorithm="RS256", headers={"kid": KID})

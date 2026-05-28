"""P0: JWKS alg allowlist must accept Supabase's optional asymmetric algs.

Supabase introduced asymmetric JWT signing keys on 2025-05-01: default RS256,
optional ES256/Ed25519. Existing allowlist in ``_decode_token`` was hardcoded
to ``{"ES256", "RS256"}`` — a token with ``alg=EdDSA`` would skip the JWKS
path and fall through to HS256 secret verification, raising
``InvalidAlgorithmError`` and producing the misleading
"JWT validation failed; dropping request to anonymous (InvalidAlgorithmError)"
log line observed in production droplet logs.

This test pins the fix: EdDSA tokens that resolve to a valid JWKS-cached
public key must verify successfully via ``_decode_token``.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from website.api.auth import _decode_token


def _make_ed25519_keypair():
    """Return (private_key, public_key) Ed25519 pair for test signing."""
    private = Ed25519PrivateKey.generate()
    return private, private.public_key()


def _sign_jwt_eddsa(private_key, payload: dict, kid: str = "test-ed25519-kid") -> str:
    """Sign a JWT with EdDSA (Ed25519) and the given kid header."""
    return pyjwt.encode(
        payload,
        private_key,
        algorithm="EdDSA",
        headers={"kid": kid},
    )


@pytest.fixture
def base_claims() -> dict:
    return {
        "sub": "550e8400-e29b-41d4-a716-446655440000",
        "email": "test@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }


def test_eddsa_token_via_jwks_path_decodes_successfully(base_claims):
    """An EdDSA-signed token with a kid resolvable in JWKS must validate.

    Pre-fix: `if jwt_alg in {"ES256","RS256"}` rejects EdDSA → falls to HS256
    fallback → InvalidAlgorithmError.

    Post-fix: EdDSA is in the allowlist → JWKS path validates → claims returned.
    """
    private, public = _make_ed25519_keypair()
    token = _sign_jwt_eddsa(private, base_claims)

    # Mock the JWKS client so get_signing_key_from_jwt returns our public key.
    fake_signing_key = MagicMock()
    fake_signing_key.key = public

    fake_jwks_client = MagicMock()
    fake_jwks_client.get_signing_key_from_jwt.return_value = fake_signing_key

    with patch("website.api.auth._get_jwks_client", return_value=fake_jwks_client):
        # No HS256 secret configured — must succeed via JWKS, not fall through.
        with patch("website.api.auth._get_jwt_secret", return_value=""):
            claims = _decode_token(token)

    assert claims["sub"] == base_claims["sub"]
    assert claims["email"] == base_claims["email"]
    assert claims["aud"] == "authenticated"

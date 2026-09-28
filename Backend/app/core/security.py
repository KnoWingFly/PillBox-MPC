"""Verifies Supabase Auth access tokens locally against the project's JWKS.

Only asymmetric algorithms are accepted. If your Supabase project still signs
tokens with the legacy HS256 shared secret, verification will fail with 401 —
migrate to JWT Signing Keys in the Supabase dashboard (Project Settings ->
JWT Keys) rather than adding HS256 here.
"""

from functools import lru_cache

import jwt
from jwt import PyJWKClient

from app.core.config import Settings

_ALLOWED_ALGORITHMS = ["ES256", "RS256"]


# One client per JWKS URL. PyJWKClient caches the fetched key set, so this
# doesn't hit Supabase on every request.
@lru_cache
def get_jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def verify_supabase_token(token: str, settings: Settings) -> dict:
    """Returns the verified claims, or raises jwt.PyJWTError subclasses."""
    signing_key = get_jwk_client(settings.jwks_url).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=_ALLOWED_ALGORITHMS,
        audience=settings.supabase_jwt_audience,
        issuer=settings.jwt_issuer,
    )

"""Token verification and device-credential hashing.

Caregiver tokens (AUTH_MODE):
- app_jwt  : HS256 tokens minted by the Mobile server (Mobile/src/server/tokens.ts,
             `new SignJWT({fid}).setSubject(userId)`), verified with the same
             JWT_ACCESS_SECRET. This is what the Expo app actually sends today.
- supabase : asymmetric (ES256/RS256) Supabase Auth tokens verified against the
             project's JWKS, per Supabase "JWT Signing Keys" docs.

Device credentials:
- device secret: high-entropy random string -> stored as SHA-256 hex; compared
  with hmac.compare_digest (constant time). A slow KDF adds nothing for
  256-bit random secrets.
- device PIN: only 4 digits, so it is hashed with scrypt + per-PIN salt and
  join attempts are rate limited (see services/pin_attempts.py).
"""

import base64
import hashlib
import hmac
import secrets
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import Settings

_SUPABASE_ALGORITHMS = ["ES256", "RS256"]
_APP_ALGORITHMS = ["HS256"]

# scrypt parameters (RFC 7914 interactive-login recommendation).
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


class TokenConfigError(RuntimeError):
    """Server misconfiguration (missing secret/URL), not a client error."""


# One client per JWKS URL. PyJWKClient caches the fetched key set, so this
# doesn't hit Supabase on every request.
@lru_cache
def get_jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def verify_app_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verifies a Mobile-server access token. Raises jwt.PyJWTError subclasses."""
    if settings.jwt_access_secret is None:
        raise TokenConfigError("JWT_ACCESS_SECRET is not set")
    return jwt.decode(
        token,
        settings.jwt_access_secret.get_secret_value(),
        algorithms=_APP_ALGORITHMS,
        options={"require": ["exp", "sub"]},
    )


def verify_supabase_token(token: str, settings: Settings) -> dict[str, Any]:
    """Blocking on a cold JWKS cache: call it from a worker thread."""
    if not settings.supabase_url:
        raise TokenConfigError("SUPABASE_URL is not set")
    signing_key = get_jwk_client(settings.jwks_url).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=_SUPABASE_ALGORITHMS,
        audience=settings.supabase_jwt_audience,
        issuer=settings.jwt_issuer,
    )


# --- device secret --------------------------------------------------------

def generate_device_secret() -> str:
    return secrets.token_urlsafe(32)


def generate_device_code() -> str:
    return f"PB-{secrets.token_hex(4).upper()}"


def hash_device_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


# Compared against when the device does not exist, so unknown and known
# device codes take the same time to reject.
_DUMMY_SECRET_HASH = hash_device_secret(secrets.token_urlsafe(32))


def verify_device_secret(provided: str | None, stored_hash: str | None) -> bool:
    candidate = hash_device_secret(provided or "")
    expected = stored_hash or _DUMMY_SECRET_HASH
    matches = hmac.compare_digest(candidate, expected)
    return matches and provided is not None and stored_hash is not None


# --- device PIN -----------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        pin.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_pin(pin: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.scrypt(
            pin.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest, expected)

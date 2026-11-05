"""Authentication: who sends a request. The browser signs in with Supabase Auth (email + password) and sends the
user's access token (a JWT) as `Authorization: Bearer <token>`; current_user checks it and returns the user.

The token is checked locally, without a call to Supabase: its signature against the project's public signing
keys (ES256, fetched once from SUPABASE_URL/auth/v1/.well-known/jwks.json and cached), its expiry, issuer and
audience. No secret is needed on the server.

Which projects (clients) a user may use is decided per endpoint (authorization), not here.
"""

import logging

import jwt
from fastapi import HTTPException, Request
from pydantic import BaseModel

from app.core.config import SUPABASE_URL
from app.core.logs import set_request_user

logger = logging.getLogger(__name__)

ALGORITHMS = ["ES256"]  # the project's asymmetric signing key (ECC P-256)
AUDIENCE = "authenticated"  # Supabase sets aud="authenticated" for signed-in users
LEEWAY_SECONDS = 30  # tolerated clock difference between Supabase and this server

_jwks: jwt.PyJWKClient | None = None  # created on first use; caches the public keys


class User(BaseModel):
    """The signed-in user who sent a request (from the access token)."""

    id: str  # Supabase user id (UUID), the token's "sub"
    email: str = ""


def _signing_keys() -> jwt.PyJWKClient:
    """The client for the Supabase project's public signing keys (created on first use, then cached)."""
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_jwk_set=True, lifespan=3600)
    return _jwks


def verify_token(token: str) -> User:
    """Check a Supabase access token and return its user.

    Args:
        token: The JWT from the Authorization header.

    Returns:
        The user the token was issued to.

    Raises:
        HTTPException: 401 if the token is invalid, expired or not from this Supabase project; 503 if the
            signing keys cannot be fetched (or SUPABASE_URL is not set).
    """
    if not SUPABASE_URL:
        raise HTTPException(503, "Sign-in is not configured on the server (SUPABASE_URL is missing).")
    try:
        key = _signing_keys().get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError as e:
        logger.error("Could not fetch the Supabase signing keys: %s", e)
        raise HTTPException(503, "Sign-in check is unavailable, please try again shortly.") from e
    except jwt.PyJWTError as e:  # malformed token or unknown key id
        raise _unauthorized("Invalid access token.") from e
    try:
        claims = jwt.decode(token, key.key, algorithms=ALGORITHMS, audience=AUDIENCE,
                            issuer=f"{SUPABASE_URL}/auth/v1", leeway=LEEWAY_SECONDS,
                            options={"require": ["exp", "sub", "aud", "iss"]})
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("Your session has expired, please sign in again.") from e
    except jwt.PyJWTError as e:
        raise _unauthorized("Invalid access token.") from e
    return User(id=claims["sub"], email=claims.get("email", ""))


def current_user(request: Request) -> User:
    """FastAPI dependency: the signed-in user who sent the request (also remembered for the request's usage log).

    Raises:
        HTTPException: 401 without a Bearer token or with an invalid one (see verify_token).
    """
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("Please sign in.")
    user = verify_token(token.strip())
    set_request_user(user.id)
    return user


def _unauthorized(message: str) -> HTTPException:
    """A 401 response asking for a Bearer token."""
    return HTTPException(401, message, headers={"WWW-Authenticate": "Bearer"})

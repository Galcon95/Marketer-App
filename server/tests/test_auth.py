"""Tests of the access token check (auth.py): a small app with one protected endpoint, and tokens signed with a key
pair made in the test instead of Supabase's, so no network and no Supabase project are needed."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import auth

SUPABASE_URL = "https://test-project.supabase.co"
KEY = ec.generate_private_key(ec.SECP256R1())  # stands in for the Supabase project's signing key
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())  # a key that is not the project's


class FakeSigningKeys:
    """Stands in for jwt.PyJWKClient: every token is checked against KEY's public key."""

    def get_signing_key_from_jwt(self, token):
        jwt.get_unverified_header(token)  # malformed tokens fail here, as with the real client
        return jwt.PyJWK.from_dict(jwt.algorithms.ECAlgorithm.to_jwk(KEY.public_key(), as_dict=True), algorithm="ES256")


def make_token(*, key=KEY, expires_in=3600, **claims) -> str:
    """A signed access token like Supabase's; keyword arguments override the claims (None removes one)."""
    payload = {"sub": "user-1", "email": "ada@example.com", "aud": "authenticated",
               "iss": f"{SUPABASE_URL}/auth/v1", "exp": int(time.time()) + expires_in} | claims
    return jwt.encode({k: v for k, v in payload.items() if v is not None}, key, algorithm="ES256")


@pytest.fixture
def client(monkeypatch):
    """A test client of an app with one endpoint that needs a signed-in user and returns it."""
    monkeypatch.setattr(auth, "SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setattr(auth, "_signing_keys", FakeSigningKeys)
    app = FastAPI()

    @app.get("/me")
    def me(user: auth.User = Depends(auth.current_user)):
        return user

    with TestClient(app) as test_client:
        yield test_client


def get_me(client, token):
    return client.get("/me", headers={"Authorization": f"Bearer {token}"})


def test_valid_token_returns_the_user(client):
    response = get_me(client, make_token())
    assert response.status_code == 200
    assert response.json() == {"id": "user-1", "email": "ada@example.com"}


def test_request_without_token_is_rejected(client):
    response = client.get("/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_expired_token_is_rejected(client):
    response = get_me(client, make_token(expires_in=-120))
    assert response.status_code == 401
    assert "expired" in response.json()["detail"]


@pytest.mark.parametrize("token", [
    make_token(key=OTHER_KEY),  # signed by someone else
    make_token(aud="anon"),  # not a signed-in user
    make_token(iss="https://other-project.supabase.co/auth/v1"),  # another Supabase project
    make_token(sub=None),  # no user id
    "not-a-jwt",
])
def test_invalid_tokens_are_rejected(client, token):
    assert get_me(client, token).status_code == 401


def test_other_schemes_are_rejected(client):
    response = client.get("/me", headers={"Authorization": f"Basic {make_token()}"})
    assert response.status_code == 401


def test_missing_configuration_is_reported(client, monkeypatch):
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    response = get_me(client, make_token())
    assert response.status_code == 503
    assert "SUPABASE_URL" in response.json()["detail"]

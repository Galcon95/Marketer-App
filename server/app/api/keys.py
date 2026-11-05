"""The signed-in user's personal API keys for the MCP servers: create (the key is shown once), list, revoke.

Only a signed-in user (Supabase access token) can manage keys; an API key itself cannot create or revoke keys.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core import api_keys
from app.core.auth import User, current_user
from app.core.schemas import ApiKey, ApiKeyCreate, ApiKeyCreated, ApiKeyInfo

router = APIRouter()


def _info(record: ApiKey) -> ApiKeyInfo:
    return ApiKeyInfo.model_validate(record.model_dump(include=set(ApiKeyInfo.model_fields)))


@router.get("/api-keys", response_model=list[ApiKeyInfo])
def list_keys(user: User = Depends(current_user)):
    """The user's keys, oldest first: name, first characters, created, last used. Never the keys themselves."""
    return [_info(k) for k in api_keys.keys_of(user)]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_key(body: ApiKeyCreate, user: User = Depends(current_user)):
    """Create a key. The response contains the key itself; it cannot be shown again later.

    Raises:
        HTTPException: 409 when the user has max_api_keys keys (limits.toml); 500 when the key cannot be saved.
    """
    try:
        record, key = api_keys.create(user, body.name)
    except api_keys.TooManyKeys as e:
        raise HTTPException(409, str(e)) from e
    except OSError as e:
        raise HTTPException(500, "The key could not be saved, please try again.") from e
    return ApiKeyCreated(**_info(record).model_dump(), key=key)


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(key_id: str, user: User = Depends(current_user)):
    """Revoke (delete) one of the user's keys; it stops working at once.

    Raises:
        HTTPException: 404 for an unknown key or another user's; 500 when the change cannot be saved.
    """
    try:
        revoked = api_keys.revoke(user, key_id)
    except OSError as e:
        raise HTTPException(500, "The key could not be revoked, please try again.") from e
    if not revoked:
        raise HTTPException(404, "Key not found.")

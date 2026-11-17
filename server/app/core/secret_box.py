"""Secrets the server keeps for a user (their Facebook Page token): encrypted before they reach the database, and
signed values the browser carries (the Facebook Login `state`).

    is_configured()     TOKEN_ENCRYPTION_KEY is set and a valid Fernet key
    encrypt(text)       → the text encrypted and authenticated (Fernet: AES-128-CBC + HMAC-SHA256)
    decrypt(token)      → the text; SecretError if it was changed or made with another key
    sign(data)          → HMAC-SHA256 of data (hex), with a key derived from TOKEN_ENCRYPTION_KEY

A database dump alone does not reveal a token: the key is only in the server's environment. Changing the key makes
the saved tokens unreadable; their users connect their Page again.
"""

import hashlib
import hmac
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core import config

logger = logging.getLogger(__name__)


class SecretError(Exception):
    """No usable key, or an encrypted value that cannot be read with it."""


def _fernet() -> Fernet | None:
    """The cipher for TOKEN_ENCRYPTION_KEY, or None if it is not set or not a valid Fernet key."""
    if not config.TOKEN_ENCRYPTION_KEY:
        return None
    try:
        return Fernet(config.TOKEN_ENCRYPTION_KEY)
    except ValueError:
        logger.error("TOKEN_ENCRYPTION_KEY is not a valid Fernet key (44 characters, URL-safe base64)")
        return None


def is_configured() -> bool:
    """True if secrets can be encrypted (a valid TOKEN_ENCRYPTION_KEY)."""
    return _fernet() is not None


def encrypt(text: str) -> str:
    """The text encrypted (a URL-safe string).

    Raises:
        SecretError: If there is no valid key.
    """
    fernet = _fernet()
    if not fernet:
        raise SecretError("TOKEN_ENCRYPTION_KEY is not set.")
    return fernet.encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    """The text of an encrypted value.

    Raises:
        SecretError: If there is no valid key, or the value was changed or encrypted with another key.
    """
    fernet = _fernet()
    if not fernet:
        raise SecretError("TOKEN_ENCRYPTION_KEY is not set.")
    try:
        return fernet.decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretError("The saved secret cannot be read with the current key.") from e


def sign(data: str) -> str:
    """HMAC-SHA256 of the data (hex), keyed with a key derived from TOKEN_ENCRYPTION_KEY (not the key itself).

    Raises:
        SecretError: If there is no valid key.
    """
    if not is_configured():
        raise SecretError("TOKEN_ENCRYPTION_KEY is not set.")
    key = hashlib.sha256(b"marketer-app signing:" + config.TOKEN_ENCRYPTION_KEY.encode()).digest()
    return hmac.new(key, data.encode(), hashlib.sha256).hexdigest()

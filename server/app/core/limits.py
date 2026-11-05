"""Limits of the app: requests per minute, cost budgets per user and for the whole app, books per user, upload size.

Read once on import from server/limits.toml; each value can be overridden by an environment variable
LIMIT_<SECTION>_<NAME> (e.g. LIMIT_PER_USER_COST_PER_DAY_USD=2, also from server/.env). The rules:
  - Fail closed: a value missing from the file keeps its default below (never "unlimited"); a missing file keeps all.
  - Every value must be a number greater than 0; anything else raises LimitsError, so the server does not start.
  - Nothing changes them while the server runs: no endpoint writes them.
The limits are enforced in api/deps.py (llm_limits) and api/sources.py (books, upload size).
"""

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from app.core.config import SERVER_DIR

LIMITS_FILE = SERVER_DIR / "limits.toml"


class LimitsError(Exception):
    """limits.toml (or a LIMIT_* variable) is unreadable or has an invalid value."""


@dataclass(frozen=True)
class PerUser:
    """Limits of each signed-in user."""

    model_requests_per_minute: int = 20
    cost_per_day_usd: float = 1.00
    cost_per_month_usd: float = 10.00
    max_books: int = 20
    max_upload_mb: int = 100
    max_api_keys: int = 10


@dataclass(frozen=True)
class AppWide:
    """Limits of all users together."""

    cost_per_day_usd: float = 20.00


@dataclass(frozen=True)
class Limits:
    per_user: PerUser
    app: AppWide


def load(path: Path = LIMITS_FILE, environ: dict[str, str] | None = None) -> Limits:
    """Read the limits from `path` (defaults for anything missing), with LIMIT_* environment overrides.

    Args:
        path: The TOML file.
        environ: Environment variables to read overrides from (default: os.environ).

    Raises:
        LimitsError: If the file cannot be parsed, has unknown names, or a value is not a number greater than 0.
    """
    environ = os.environ if environ is None else environ
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise LimitsError(f"{path.name} cannot be read: {e}") from e
    unknown = set(data) - {"per_user", "app"}
    if unknown:
        raise LimitsError(f"{path.name}: unknown section(s) {', '.join(sorted(unknown))}")
    return Limits(per_user=_section(PerUser, "per_user", data.get("per_user", {}), environ, path),
                  app=_section(AppWide, "app", data.get("app", {}), environ, path))


def _section(cls, name: str, values: dict, environ, path: Path):
    """One section as its dataclass: file values over the defaults, LIMIT_* variables over both, all checked."""
    known = {f.name: f for f in fields(cls)}
    unknown = set(values) - set(known)
    if unknown:
        raise LimitsError(f"{path.name} [{name}]: unknown name(s) {', '.join(sorted(unknown))}")
    result = {}
    for key, field in known.items():
        env_name = f"LIMIT_{name}_{key}".upper()
        raw, where = (environ[env_name], env_name) if env_name in environ else (values.get(key), f"[{name}] {key}")
        if raw is None:
            continue  # the default
        try:
            value = field.type(raw) if not isinstance(raw, bool) else None
        except (TypeError, ValueError):
            value = None
        if value is None or value <= 0 or (field.type is int and float(raw) != value):
            raise LimitsError(f"{where} must be a {'whole ' if field.type is int else ''}number greater than 0, "
                              f"not {raw!r}")
        result[key] = value
    return cls(**result)


LIMITS = load()

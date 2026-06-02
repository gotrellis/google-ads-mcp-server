"""Environment-variable configuration loaded at server start.

The parent process (clio-idx) writes an authorized_user JSON credentials
file to a stable per-connector path and passes its location via
``GOOGLE_APPLICATION_CREDENTIALS``. This module is the single point that
reads those vars — keep the contract here so changes on the clio-idx side
have one place to update on this side.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required environment variables are missing or invalid."""


@dataclass(frozen=True)
class ServerConfig:
    credentials_path: str
    developer_token: str
    # ``None`` when no MCC is configured. Passing a non-numeric placeholder
    # like ``"google_ads"`` to the API surfaces as a cryptic INVALID_CUSTOMER_ID,
    # so we only honor numeric values — anything else is dropped at the source.
    login_customer_id: str | None


def load_config() -> ServerConfig:
    """Read env vars and validate minimal required inputs.

    Raises:
        ConfigError: When the developer token or credentials file are absent.
                     A missing file path is a hard error because every API call
                     downstream would fail with a less actionable message.
    """
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not credentials_path:
        raise ConfigError(
            "GOOGLE_APPLICATION_CREDENTIALS is not set. The parent process is "
            "responsible for writing an authorized_user JSON file and setting "
            "this env var — see clio-idx api/utils/mcp_config.py:"
            "build_google_ads_subprocess_env."
        )
    if not os.path.exists(credentials_path):
        raise ConfigError(
            f"GOOGLE_APPLICATION_CREDENTIALS path does not exist: {credentials_path!r}"
        )

    developer_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    if not developer_token:
        raise ConfigError(
            "GOOGLE_ADS_DEVELOPER_TOKEN is not set. Configure it in the parent "
            "process's Django settings and re-spawn this server."
        )

    raw_login_customer_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "")
    login_customer_id = (
        raw_login_customer_id if raw_login_customer_id.isdigit() else None
    )

    return ServerConfig(
        credentials_path=credentials_path,
        developer_token=developer_token,
        login_customer_id=login_customer_id,
    )

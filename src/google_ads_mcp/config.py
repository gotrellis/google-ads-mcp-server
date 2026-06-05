"""Environment-variable configuration loaded at server start.

The parent process (clio-idx) passes the OAuth2 refresh-token credential
directly as environment variables — ``GOOGLE_ADS_CLIENT_ID``,
``GOOGLE_ADS_CLIENT_SECRET`` and ``GOOGLE_ADS_REFRESH_TOKEN`` — rather than
staging an authorized_user JSON file on disk. This module is the single
point that reads those vars — keep the contract here so changes on the
clio-idx side have one place to update on this side.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required environment variables are missing or invalid."""


@dataclass(frozen=True)
class ServerConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    developer_token: str
    # ``None`` when no MCC is configured. Passing a non-numeric placeholder
    # like ``"google_ads"`` to the API surfaces as a cryptic INVALID_CUSTOMER_ID,
    # so we only honor numeric values — anything else is dropped at the source.
    login_customer_id: str | None


def load_config() -> ServerConfig:
    """Read env vars and validate minimal required inputs.

    Raises:
        ConfigError: When the developer token or any of the OAuth2 credential
                     vars are absent. Each is a hard error because every API
                     call downstream would otherwise fail with a less
                     actionable message.
    """
    # The OAuth2 refresh-token credential, passed in-memory by the parent
    # process. We use the same names the official google-ads SDK recognizes.
    oauth_vars = {
        "GOOGLE_ADS_CLIENT_ID": os.environ.get("GOOGLE_ADS_CLIENT_ID", ""),
        "GOOGLE_ADS_CLIENT_SECRET": os.environ.get("GOOGLE_ADS_CLIENT_SECRET", ""),
        "GOOGLE_ADS_REFRESH_TOKEN": os.environ.get("GOOGLE_ADS_REFRESH_TOKEN", ""),
    }
    missing = [name for name, value in oauth_vars.items() if not value]
    if missing:
        raise ConfigError(
            f"Missing required OAuth credential env var(s): {', '.join(sorted(missing))}. "
            "The parent process is responsible for setting these — see clio-idx "
            "api/utils/mcp_config.py:build_google_ads_subprocess_env."
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
        client_id=oauth_vars["GOOGLE_ADS_CLIENT_ID"],
        client_secret=oauth_vars["GOOGLE_ADS_CLIENT_SECRET"],
        refresh_token=oauth_vars["GOOGLE_ADS_REFRESH_TOKEN"],
        developer_token=developer_token,
        login_customer_id=login_customer_id,
    )

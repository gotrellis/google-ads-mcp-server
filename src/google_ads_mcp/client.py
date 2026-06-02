"""Thin wrapper around the official google-ads Python client.

We construct ``GoogleAdsClient`` from the env-var-derived
``ServerConfig`` rather than from the SDK's default YAML loader so the
credentials path is explicit and the contract with clio-idx stays
testable.

The wrapper is intentionally small. Tool implementations call into the
underlying ``GoogleAdsClient.get_service(...)`` directly so they can use
the SDK's typed request objects without an extra abstraction layer.
"""

from __future__ import annotations

import json
from functools import lru_cache

from google.ads.googleads.client import GoogleAdsClient

from .config import ConfigError, ServerConfig


@lru_cache(maxsize=1)
def _load_authorized_user(credentials_path: str) -> dict:
    """Read the authorized_user JSON exactly once per process.

    The parent writes a stable per-connector path, so caching is safe
    within a single subprocess invocation. Across spawns, the cache is
    moot because each spawn is a fresh Python process.
    """
    with open(credentials_path, encoding="utf-8") as fh:
        data = json.load(fh)
    required = {"client_id", "client_secret", "refresh_token"}
    missing = required - data.keys()
    if missing:
        raise ConfigError(
            f"authorized_user JSON at {credentials_path!r} is missing keys: {sorted(missing)}"
        )
    return data


def build_client(config: ServerConfig) -> GoogleAdsClient:
    """Construct a GoogleAdsClient using OAuth refresh-token credentials.

    The official client accepts a ``credentials`` dict alongside the
    developer token. We pass the authorized_user payload directly rather
    than going through ``google.auth.default()`` so any credential error
    surfaces with a precise file path instead of an opaque ADC message.
    """
    creds = _load_authorized_user(config.credentials_path)

    init_kwargs: dict = {
        "developer_token": config.developer_token,
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "use_proto_plus": True,
    }
    if config.login_customer_id:
        init_kwargs["login_customer_id"] = config.login_customer_id

    return GoogleAdsClient.load_from_dict(init_kwargs)

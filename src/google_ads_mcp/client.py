"""Thin wrapper around the official google-ads Python client.

We construct ``GoogleAdsClient`` from the env-var-derived
``ServerConfig`` rather than from the SDK's default YAML loader so the
credentials are explicit and the contract with clio-idx stays testable.

The wrapper is intentionally small. Tool implementations call into the
underlying ``GoogleAdsClient.get_service(...)`` directly so they can use
the SDK's typed request objects without an extra abstraction layer.
"""

from __future__ import annotations

from google.ads.googleads.client import GoogleAdsClient

from .config import ServerConfig


def build_client(config: ServerConfig) -> GoogleAdsClient:
    """Construct a GoogleAdsClient using OAuth refresh-token credentials.

    The official client accepts a ``credentials`` dict alongside the
    developer token. We pass the OAuth2 refresh-token credential directly
    from the env-var-derived config rather than going through
    ``google.auth.default()`` or a credentials file on disk.
    """
    init_kwargs: dict = {
        "developer_token": config.developer_token,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "refresh_token": config.refresh_token,
        "use_proto_plus": True,
    }
    if config.login_customer_id:
        init_kwargs["login_customer_id"] = config.login_customer_id

    return GoogleAdsClient.load_from_dict(init_kwargs)

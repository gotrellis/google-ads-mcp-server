"""Tests for env-var-based credential loading.

Run with: ``uv run python -m unittest discover -s tests``
"""

from __future__ import annotations

import unittest
from unittest import mock

from google_ads_mcp.client import build_client
from google_ads_mcp.config import ConfigError, ServerConfig, load_config

_FULL_ENV = {
    "GOOGLE_ADS_CLIENT_ID": "client-id-123",
    "GOOGLE_ADS_CLIENT_SECRET": "client-secret-xyz",
    "GOOGLE_ADS_REFRESH_TOKEN": "rt-xyz",
    "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token-abc",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
}


class LoadConfigTests(unittest.TestCase):
    def test_reads_oauth_credentials_from_env(self):
        with mock.patch.dict("os.environ", _FULL_ENV, clear=True):
            config = load_config()

        self.assertEqual(config.client_id, "client-id-123")
        self.assertEqual(config.client_secret, "client-secret-xyz")
        self.assertEqual(config.refresh_token, "rt-xyz")
        self.assertEqual(config.developer_token, "dev-token-abc")
        self.assertEqual(config.login_customer_id, "1234567890")

    def test_non_numeric_login_customer_id_is_dropped(self):
        env = {**_FULL_ENV, "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "google_ads"}
        with mock.patch.dict("os.environ", env, clear=True):
            config = load_config()
        self.assertIsNone(config.login_customer_id)

    def test_missing_login_customer_id_is_none(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "GOOGLE_ADS_LOGIN_CUSTOMER_ID"}
        with mock.patch.dict("os.environ", env, clear=True):
            config = load_config()
        self.assertIsNone(config.login_customer_id)

    def test_missing_oauth_var_raises(self):
        for var in ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN"):
            env = {k: v for k, v in _FULL_ENV.items() if k != var}
            with self.subTest(missing=var):
                with mock.patch.dict("os.environ", env, clear=True):
                    with self.assertRaises(ConfigError) as ctx:
                        load_config()
                self.assertIn(var, str(ctx.exception))

    def test_missing_developer_token_raises(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "GOOGLE_ADS_DEVELOPER_TOKEN"}
        with mock.patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ConfigError) as ctx:
                load_config()
        self.assertIn("GOOGLE_ADS_DEVELOPER_TOKEN", str(ctx.exception))


class BuildClientTests(unittest.TestCase):
    def _config(self, login_customer_id="1234567890"):
        return ServerConfig(
            client_id="client-id-123",
            client_secret="client-secret-xyz",
            refresh_token="rt-xyz",
            developer_token="dev-token-abc",
            login_customer_id=login_customer_id,
        )

    @mock.patch("google_ads_mcp.client.GoogleAdsClient.load_from_dict")
    def test_passes_oauth_credentials_from_config(self, load_from_dict):
        # Patch the SDK loader so we assert the in-memory credential contract
        # without triggering a real OAuth token refresh.
        build_client(self._config())

        kwargs = load_from_dict.call_args.args[0]
        self.assertEqual(kwargs["client_id"], "client-id-123")
        self.assertEqual(kwargs["client_secret"], "client-secret-xyz")
        self.assertEqual(kwargs["refresh_token"], "rt-xyz")
        self.assertEqual(kwargs["developer_token"], "dev-token-abc")
        self.assertEqual(kwargs["login_customer_id"], "1234567890")
        self.assertTrue(kwargs["use_proto_plus"])

    @mock.patch("google_ads_mcp.client.GoogleAdsClient.load_from_dict")
    def test_omits_login_customer_id_when_none(self, load_from_dict):
        build_client(self._config(login_customer_id=None))
        kwargs = load_from_dict.call_args.args[0]
        self.assertNotIn("login_customer_id", kwargs)


if __name__ == "__main__":
    unittest.main()

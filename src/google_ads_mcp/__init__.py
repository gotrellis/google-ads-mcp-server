"""Google Ads MCP server package.

A stdio-transport MCP server that exposes Google Ads API operations as
tools the parent process can invoke. Spawned by clio-idx (see
``api/utils/mcp_config.py``) with OAuth credentials passed via env vars:

- ``GOOGLE_APPLICATION_CREDENTIALS`` — path to an authorized_user JSON
  containing ``client_id`` / ``client_secret`` / ``refresh_token``.
- ``GOOGLE_ADS_DEVELOPER_TOKEN`` — the developer token for the Google
  Ads API.
- ``GOOGLE_ADS_LOGIN_CUSTOMER_ID`` — optional MCC customer ID, only set
  when the per-connector value is numeric (passing a placeholder string
  causes Google Ads API errors).
"""

__version__ = "0.1.0"

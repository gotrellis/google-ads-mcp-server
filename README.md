# google-ads-mcp

Model Context Protocol server for the Google Ads API. Spawned as a
stdio subprocess by [clio-idx](https://github.com/gotrellis/clio-idx)
(`api/utils/mcp_config.py`) with per-org OAuth credentials passed as
environment variables.

Pairs with `clio-idx`'s `feat/google-ads-oauth` branch (and
`clio-fe`'s `feat/google-ads-oauth-fe`).

## How it's wired

clio-idx passes the per-connector OAuth `client_id` / `client_secret` /
`refresh_token` directly as environment variables (in-memory, no
credentials file on disk), then spawns `google-ads-mcp` over stdio.
This server reads those env vars, builds a `GoogleAdsClient`, and
exposes tools via the MCP protocol.

### Required env vars

| Var | Meaning |
|---|---|
| `GOOGLE_ADS_CLIENT_ID` | OAuth2 client ID. |
| `GOOGLE_ADS_CLIENT_SECRET` | OAuth2 client secret. |
| `GOOGLE_ADS_REFRESH_TOKEN` | OAuth2 refresh token for the connected account. |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Google Ads API developer token. |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | Optional MCC customer ID. Only honored when numeric. |

## Tools

| Name | Purpose |
|---|---|
| `list_accessible_customers` | List customer accounts the user can access. |
| `gaql_search` | Run a GAQL query against a specific customer. |

More tools (create_campaign, update_ad, etc.) are intended additions —
each is a module in `src/google_ads_mcp/tools/` exporting `TOOL` and
`call(client, arguments)`. Register by adding to `TOOL_MODULES` in
`server.py`.

## Local install (for clio-idx development)

In `clio-idx`'s `pyproject.toml`:

```toml
dependencies = [
    # …
    "google-ads-mcp",
]

[tool.uv.sources]
google-ads-mcp = { path = "../google-ads-mcp-server", editable = true }
```

Then `uv sync` and the `google-ads-mcp` executable appears in
`.venv/bin/`.

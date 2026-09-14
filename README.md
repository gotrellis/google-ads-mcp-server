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
| `list_accessible_customers` | List the customer accounts the authenticated user can access. |
| `search` | Structured GAQL read: `resource` + `fields` (+ optional `conditions` / `orderings` / `limit`); the server assembles the GAQL. Rows are keyed by the selected dotted field names (enums as names). This is the read path clio-idx uses. |
| `gaql_search` | Run a raw GAQL query string against a customer. |
| `set_campaign_status` | Pause or enable a campaign (`CampaignService.mutate_campaigns`, `status` only). |
| `update_campaign_budget` | Update a campaign budget's `amount_micros` (`CampaignBudgetService.mutate_campaign_budgets`). The budget is the shared `CampaignBudget` entity. |
| `set_campaign_bidding_strategy` | Switch a campaign's standard bidding strategy — `MANUAL_CPC`, `MAXIMIZE_CONVERSIONS` (+`target_cpa_micros`), `MAXIMIZE_CONVERSION_VALUE` (+`target_roas`), `TARGET_SPEND` (`CampaignService.mutate_campaigns`, bidding oneof). |
| `update_campaign` | Edit campaign metadata — any of `name` (rename), `start_date`, `end_date` (YYYY-MM-DD). Masks only the fields provided (`CampaignService.mutate_campaigns`). |
| `create_label` | Create an account-level `Label` (`LabelService.mutate_labels`); optional `description` / `background_color`. Returns the new `label_id`. |
| `apply_campaign_label` | Attach an existing label to a campaign — `campaign_id` + `label_id` (`CampaignLabelService.mutate_campaign_labels`, create). |
| `remove_campaign_label` | Detach a label from a campaign — `campaign_id` + `label_id` (`CampaignLabelService.mutate_campaign_labels`, remove). |
| `update_ad_group` | Edit an ad group — any of `status` (ENABLED/PAUSED), `name`, `cpc_bid_micros`. Masks only the fields provided (`AdGroupService.mutate_ad_groups`). |
| `update_ad_group_ad` | Pause or enable an individual ad — `ad_group_id` + `ad_id`, `status` only (`AdGroupAdService.mutate_ad_group_ads`). Does not edit creative. |
| `update_ad_group_criterion` | Edit a keyword criterion — any of `status`, `cpc_bid_micros`; addressed by `ad_group_id` + `criterion_id` (`AdGroupCriterionService.mutate_ad_group_criteria`). |
| `add_negative_keyword` | Add a negative keyword at ad-group level (`AdGroupCriterionService`) or campaign level (`CampaignCriterionService`) — pass exactly one of `ad_group_id` / `campaign_id`. `match_type` EXACT/PHRASE/BROAD, default EXACT. |
| `remove_negative_keyword` | Remove a negative keyword — exactly one of `ad_group_id` / `campaign_id`, plus the `criterion_id` from a read where `negative=true`. |

Writes call the official `google-ads` SDK mutate services directly. Pass
`validate_only=true` on a write for a dry run (the API validates without
applying; no resource names are returned).

### Adding a tool

Drop a module in `src/google_ads_mcp/tools/` exporting `TOOL` (an
`mcp.types.Tool`) and `call(client, arguments) -> list[TextContent]`, then add
it to `TOOL_MODULES` in `server.py`. **Let errors propagate** — raise rather
than returning an `{"error": ...}` payload — so the MCP SDK marks the result
`isError=true`, which is how the parent (clio-idx) detects failures.

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

## Tests

```bash
uv run python -m unittest discover -s tests
```

`tests/test_server.py` builds the server for real, so an `mcp` release that
changes the decorator API fails the suite instead of only failing at runtime.

### MCP SDK version

The `mcp` dependency is capped at `<2.0.0`. `mcp` 2.x removed the
`Server.list_tools()` / `Server.call_tool()` decorators this server registers
its handlers with, so `_build_server()` raises `AttributeError` on startup
under 2.x. Lifting the cap means porting `server.py` to the 2.x API first.

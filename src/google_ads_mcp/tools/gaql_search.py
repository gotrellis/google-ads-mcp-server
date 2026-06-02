"""Tool: gaql_search.

Executes an arbitrary GAQL (Google Ads Query Language) query against a
specific customer account. This is the workhorse for reads — campaigns,
ad groups, performance metrics, segments — anything GAQL can express.

Example query (passed by the LLM):
    SELECT campaign.id, campaign.name, campaign.status
    FROM campaign
    WHERE campaign.status = 'ENABLED'
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.client import GoogleAdsClient
from google.protobuf.json_format import MessageToDict
from mcp.types import TextContent, Tool

TOOL = Tool(
    name="gaql_search",
    description=(
        "Run a GAQL (Google Ads Query Language) query against a specific "
        "customer account. Returns the rows as a list of dicts. Use this for "
        "all reads from Google Ads — campaigns, ad groups, ads, keywords, "
        "metrics, segments. Reference: "
        "https://developers.google.com/google-ads/api/docs/query/overview"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": (
                    "The Google Ads customer ID to query, with no dashes (e.g. "
                    "'1234567890'). Obtain valid IDs from list_accessible_customers."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "A valid GAQL query string. Must include SELECT and FROM. "
                    "WHERE / ORDER BY / LIMIT are optional."
                ),
            },
        },
        "required": ["customer_id", "query"],
    },
)


def call(client: GoogleAdsClient, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    query = arguments["query"]

    service = client.get_service("GoogleAdsService")
    stream = service.search_stream(customer_id=customer_id, query=query)

    rows: list[dict] = []
    for batch in stream:
        for row in batch.results:
            # ``preserving_proto_field_name=True`` keeps the API's snake_case
            # naming so downstream consumers don't have to remap fields.
            rows.append(MessageToDict(row._pb, preserving_proto_field_name=True))

    return [
        TextContent(
            type="text",
            text=json.dumps({"rows": rows, "row_count": len(rows)}),
        )
    ]

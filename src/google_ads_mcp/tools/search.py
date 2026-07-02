"""Tool: search — structured GAQL read.

Mirrors the contract of the official google-ads-mcp ``search`` tool so the
parent (clio-idx ``graph_explorer/primitives/google_ads_query``) works
unchanged after the connector is re-pointed at this server: the caller sends
structured arguments (``customer_id``, ``fields``, ``resource`` + optional
``conditions`` / ``orderings`` / ``limit``) and this tool assembles the GAQL
itself. There is deliberately NO raw ``query`` parameter — that is what the
separate ``gaql_search`` tool is for.

Output shape: one dict per row, keyed by exactly the requested ``fields`` (e.g.
``{"campaign.id": 1, "campaign.status": "ENABLED"}``) with enum values rendered
as their names. We format by the caller's ``fields`` — NOT the response
``field_mask`` — because the API's field_mask omits id / resource-name fields
(``campaign.id``, ``campaign.campaign_budget``, ...), which would silently blank
the very columns a write action needs to target a customer/budget. For the same
reason the query does not set ``omit_unselected_resource_names``.
"""

from __future__ import annotations

import json
from typing import Any

import proto
from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message

TOOL = Tool(
    name="search",
    description=(
        "Run a structured Google Ads search (GAQL) against one customer account. "
        "Provide `resource` (the FROM, e.g. 'campaign'), `fields` (dotted field "
        "names to SELECT, e.g. ['campaign.id','campaign.name','metrics.clicks']), "
        "and optional `conditions` (WHERE clauses, AND-combined), `orderings` "
        "(ORDER BY) and `limit`. Returns rows keyed by the selected dotted field "
        "names. Use for all reads — campaigns, ad groups, ads, keywords, metrics, "
        "segments. Obtain customer IDs from list_accessible_customers."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID to query, no dashes (e.g. '1234567890').",
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Dotted field names to SELECT (e.g. 'campaign.name', 'metrics.clicks').",
            },
            "resource": {
                "type": "string",
                "description": "The FROM resource, e.g. 'campaign', 'ad_group', 'keyword_view'.",
            },
            "conditions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "WHERE clauses, combined with AND (e.g. \"campaign.status = 'ENABLED'\").",
            },
            "orderings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ORDER BY clauses (e.g. 'metrics.clicks DESC').",
            },
            "limit": {"type": "integer", "description": "Maximum number of rows to return."},
        },
        "required": ["customer_id", "fields", "resource"],
    },
)


def _build_query(
    fields: list[str],
    resource: str,
    conditions: list[str] | None = None,
    orderings: list[str] | None = None,
    limit: int | None = None,
) -> str:
    """Assemble a GAQL query string from structured parts.

    Deliberately does NOT append ``PARAMETERS omit_unselected_resource_names=true``:
    that parameter makes the API drop id / resource-name fields (``campaign.id``,
    ``campaign.campaign_budget``, ...) from the response field_mask, which blanked
    those columns. Rows are formatted by the requested ``fields`` (see ``call``), so
    the extra auto-returned resource_names are simply ignored.
    """
    parts = [f"SELECT {','.join(fields)} FROM {resource}"]
    if conditions:
        parts.append(f" WHERE {' AND '.join(conditions)}")
    if orderings:
        parts.append(f" ORDER BY {','.join(orderings)}")
    if limit:
        parts.append(f" LIMIT {int(limit)}")
    return "".join(parts)


def _format_value(value: Any) -> Any:
    """Render a single field value JSON-serializably (enums → names)."""
    if isinstance(value, proto.Enum):
        return value.name
    if isinstance(value, proto.Message):
        return proto.Message.to_dict(value)
    if hasattr(value, "__iter__") and not isinstance(value, (str | bytes)):
        return [_format_value(v) for v in value]
    return value


def _get_nested_attr(obj: Any, path: str) -> Any:
    """Resolve a dotted field path (e.g. 'campaign.id') against a proto row."""
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _format_row(row: Any, paths: Any) -> dict[str, Any]:
    """Flatten one result row into ``{dotted_field: value}`` for the given paths."""
    return {path: _format_value(_get_nested_attr(row, path)) for path in paths}


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    fields = arguments["fields"]
    query = _build_query(
        fields,
        arguments["resource"],
        conditions=arguments.get("conditions"),
        orderings=arguments.get("orderings"),
        limit=arguments.get("limit"),
    )

    service = client.get_service("GoogleAdsService")
    try:
        stream = service.search_stream(customer_id=customer_id, query=query)
        rows: list[dict[str, Any]] = []
        for batch in stream:
            for row in batch.results:
                # Format by the REQUESTED fields, not batch.field_mask.paths: the API's
                # field_mask omits id / resource-name fields, so relying on it drops
                # campaign.id / campaign.campaign_budget and blanks the IDs writes need.
                rows.append(_format_row(row, fields))
    except GoogleAdsException as exc:
        # Re-raise with a clean message; server.py lets it propagate so the SDK
        # marks the result isError=True (the parent relies on that to detect
        # read failures rather than silently parsing an error as zero rows).
        raise RuntimeError(google_ads_error_message(exc)) from exc

    return [TextContent(type="text", text=json.dumps({"rows": rows, "row_count": len(rows)}))]

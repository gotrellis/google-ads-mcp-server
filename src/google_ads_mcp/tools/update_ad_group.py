"""Tool: update_ad_group — edit ad-group status, name, and/or default bid.

Updates scalar ``AdGroup`` fields via ``AdGroupService.mutate_ad_groups`` with an
update mask covering only the fields actually provided. Supported fields:

    status          — ENABLED or PAUSED (pause/enable the ad group)
    name            — the ad-group name (rename)
    cpc_bid_micros  — the ad group's default max CPC bid, in micros

The ad-group id comes from an upstream read (``ad_group.id``). At least one
editable field must be provided. ``validate_only=true`` performs a dry run: the
API validates the change without applying it and returns no resource names.
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message
from ._limits import max_cpc_bid_micros

_ALLOWED_STATUSES = ("ENABLED", "PAUSED")


TOOL = Tool(
    name="update_ad_group",
    description=(
        "Edit a Google Ads ad group (AdGroupService.mutate_ad_groups). Provide "
        "any of: status (ENABLED/PAUSED), name (rename), cpc_bid_micros (default "
        "max CPC bid in micros of the account currency). Only the fields you pass "
        "are updated; at least one is required. Pass validate_only=true for a dry "
        "run that validates without applying."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID owning the ad group, no dashes (e.g. '1234567890').",
            },
            "ad_group_id": {
                "type": "string",
                "description": "Ad group ID to update (the numeric ad_group.id from a read).",
            },
            "status": {
                "type": "string",
                "enum": list(_ALLOWED_STATUSES),
                "description": "New status: ENABLED or PAUSED (optional).",
            },
            "name": {"type": "string", "description": "New ad-group name (optional)."},
            "cpc_bid_micros": {
                "type": "integer",
                "description": "New default max CPC bid in micros (account currency * 1,000,000) (optional).",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate the change without applying it. Default false.",
            },
        },
        "required": ["customer_id", "ad_group_id"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    ad_group_id = _last_segment(arguments["ad_group_id"])
    validate_only = bool(arguments.get("validate_only", False))

    service = client.get_service("AdGroupService")
    operation = client.get_type("AdGroupOperation")
    ad_group = operation.update
    ad_group.resource_name = service.ad_group_path(customer_id, ad_group_id)

    # Set only the provided fields and mask exactly those.
    updated_fields: list[str] = []

    status = arguments.get("status")
    if status is not None and str(status).strip():
        status = str(status).strip().upper()
        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {list(_ALLOWED_STATUSES)}, got {arguments.get('status')!r}")
        ad_group.status = client.enums.AdGroupStatusEnum[status]
        updated_fields.append("status")

    name = arguments.get("name")
    if name is not None and str(name).strip():
        ad_group.name = str(name).strip()
        updated_fields.append("name")

    raw_bid = arguments.get("cpc_bid_micros")
    if raw_bid is not None and str(raw_bid).strip():
        try:
            cpc_bid_micros = int(raw_bid)
        except (TypeError, ValueError):
            raise ValueError(f"cpc_bid_micros must be an integer, got {raw_bid!r}") from None
        if cpc_bid_micros < 0:
            raise ValueError(f"cpc_bid_micros must be >= 0, got {cpc_bid_micros}")
        ceiling = max_cpc_bid_micros()
        if cpc_bid_micros > ceiling:
            raise ValueError(
                f"cpc_bid_micros {cpc_bid_micros} exceeds the safety ceiling {ceiling} "
                f"(~{ceiling // 1_000_000:,} in account currency). Set GOOGLE_ADS_MAX_CPC_BID_MICROS to raise it."
            )
        ad_group.cpc_bid_micros = cpc_bid_micros
        updated_fields.append("cpc_bid_micros")

    if not updated_fields:
        raise ValueError("update_ad_group requires at least one of: status, name, cpc_bid_micros")

    for path in updated_fields:
        operation.update_mask.paths.append(path)

    request = client.get_type("MutateAdGroupsRequest")
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only
    try:
        response = service.mutate_ad_groups(request=request)
    except GoogleAdsException as exc:
        raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    payload = {
        "customer_id": customer_id,
        "ad_group_id": ad_group_id,
        "updated_fields": updated_fields,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

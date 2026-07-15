"""Tool: update_ad_group_ad — pause or enable an individual ad.

Sets ``ad_group_ad.status`` to ENABLED or PAUSED via
``AdGroupAdService.mutate_ad_group_ads`` with an update mask covering only
``status``. An ad is addressed by the compound ``{ad_group_id}~{ad_id}``, so both
ids are required (from a read of ``ad_group.id`` and ``ad_group_ad.ad.id``).

Only status is editable here — editing ad *creative* (headlines, descriptions)
is a separate, larger surface not covered by this tool. ``validate_only=true``
performs a dry run (no resource names returned).
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message

_ALLOWED_STATUSES = ("ENABLED", "PAUSED")


TOOL = Tool(
    name="update_ad_group_ad",
    description=(
        "Pause or enable an individual Google Ads ad (AdGroupAdService."
        "mutate_ad_group_ads, update_mask on status only). Sets the ad's status "
        "to ENABLED or PAUSED. Requires ad_group_id and ad_id (an ad is addressed "
        "by ad_group_id~ad_id). Pass validate_only=true for a dry run. This tool "
        "does not edit ad creative — only its status."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID owning the ad, no dashes (e.g. '1234567890').",
            },
            "ad_group_id": {
                "type": "string",
                "description": "Ad group ID containing the ad (the numeric ad_group.id from a read).",
            },
            "ad_id": {
                "type": "string",
                "description": "Ad ID to update (the numeric ad_group_ad.ad.id from a read).",
            },
            "status": {
                "type": "string",
                "enum": list(_ALLOWED_STATUSES),
                "description": "New status: ENABLED or PAUSED.",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate the change without applying it. Default false.",
            },
        },
        "required": ["customer_id", "ad_group_id", "ad_id", "status"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    ad_group_id = _last_segment(arguments["ad_group_id"])
    ad_id = _last_segment(arguments["ad_id"])
    status = str(arguments["status"]).strip().upper()
    validate_only = bool(arguments.get("validate_only", False))

    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"status must be one of {list(_ALLOWED_STATUSES)}, got {arguments.get('status')!r}")

    service = client.get_service("AdGroupAdService")
    operation = client.get_type("AdGroupAdOperation")
    ad_group_ad = operation.update
    ad_group_ad.resource_name = service.ad_group_ad_path(customer_id, ad_group_id, ad_id)
    ad_group_ad.status = client.enums.AdGroupAdStatusEnum[status]
    operation.update_mask.paths.append("status")

    request = client.get_type("MutateAdGroupAdsRequest")
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only
    try:
        response = service.mutate_ad_group_ads(request=request)
    except GoogleAdsException as exc:
        raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    payload = {
        "customer_id": customer_id,
        "ad_group_id": ad_group_id,
        "ad_id": ad_id,
        "status": status,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

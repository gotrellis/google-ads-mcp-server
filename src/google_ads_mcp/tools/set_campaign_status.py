"""Tool: set_campaign_status — pause or enable a campaign.

Sets ``campaign.status`` to ENABLED or PAUSED via
``CampaignService.mutate_campaigns`` with an update mask covering only
``status``. The campaign id comes from an upstream read (``campaign.id``).

``validate_only=true`` performs a dry run: the API validates the change without
applying it and returns no resource names (so ``mutated`` is false).
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message

_ALLOWED_STATUSES = ("ENABLED", "PAUSED")


TOOL = Tool(
    name="set_campaign_status",
    description=(
        "Pause or enable a Google Ads campaign. Sets the campaign's status to "
        "ENABLED or PAUSED (CampaignService.mutate_campaigns, update_mask on "
        "status only). Pass validate_only=true for a dry run that validates the "
        "change without applying it."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID owning the campaign, no dashes (e.g. '1234567890').",
            },
            "campaign_id": {
                "type": "string",
                "description": "Campaign ID to update (the numeric campaign.id from a read).",
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
        "required": ["customer_id", "campaign_id", "status"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    campaign_id = _last_segment(arguments["campaign_id"])
    status = str(arguments["status"]).strip().upper()
    validate_only = bool(arguments.get("validate_only", False))

    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"status must be one of {list(_ALLOWED_STATUSES)}, got {arguments.get('status')!r}")

    service = client.get_service("CampaignService")
    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = service.campaign_path(customer_id, campaign_id)
    campaign.status = client.enums.CampaignStatusEnum[status]
    operation.update_mask.paths.append("status")

    try:
        response = service.mutate_campaigns(
            customer_id=customer_id, operations=[operation], validate_only=validate_only
        )
    except GoogleAdsException as exc:
        raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    payload = {
        "customer_id": customer_id,
        "campaign_id": campaign_id,
        "status": status,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

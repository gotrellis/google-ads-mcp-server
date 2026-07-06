"""Tool: update_campaign — edit campaign metadata (name, start/end dates).

Updates scalar ``Campaign`` fields via ``CampaignService.mutate_campaigns`` with
an update mask covering only the fields actually provided. Supported fields:

    name        — the campaign name
    start_date  — serving start date (YYYY-MM-DD; YYYYMMDD also accepted)
    end_date    — serving end date (YYYY-MM-DD; YYYYMMDD also accepted)

At least one editable field must be provided. These are all scalar (string)
fields, so the mask lists the field name directly — no subfield handling (unlike
the bidding-strategy oneof). ``validate_only=true`` performs a dry run: the API
validates the change without applying it and returns no resource names.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message

# Editable scalar fields, in a stable order for the update mask / response.
_DATE_FIELDS = ("start_date", "end_date")


TOOL = Tool(
    name="update_campaign",
    description=(
        "Edit Google Ads campaign metadata (CampaignService.mutate_campaigns). "
        "Provide any of: name (rename), start_date, end_date (YYYY-MM-DD). Only "
        "the fields you pass are updated. At least one is required. Pass "
        "validate_only=true for a dry run that validates without applying."
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
            "name": {"type": "string", "description": "New campaign name (optional)."},
            "start_date": {
                "type": "string",
                "description": "New serving start date, YYYY-MM-DD (optional).",
            },
            "end_date": {
                "type": "string",
                "description": "New serving end date, YYYY-MM-DD (optional). Omit to leave unchanged.",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate the change without applying it. Default false.",
            },
        },
        "required": ["customer_id", "campaign_id"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def _normalize_date(value: Any) -> str:
    """Accept YYYY-MM-DD or YYYYMMDD; return the extended YYYY-MM-DD form.

    Uses ``strptime`` so the value must be a real calendar date — an impossible
    date (month 13, day 32) raises here before the API call, giving a clear
    message instead of an opaque INVALID_ARGUMENT.
    """
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"date must be a real calendar date in YYYY-MM-DD (or YYYYMMDD), got {value!r}")


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    campaign_id = _last_segment(arguments["campaign_id"])
    validate_only = bool(arguments.get("validate_only", False))

    service = client.get_service("CampaignService")
    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = service.campaign_path(customer_id, campaign_id)

    # Set only the provided fields and mask exactly those. These are scalar
    # string fields, so the mask path is the field name itself.
    updated_fields: list[str] = []
    name = arguments.get("name")
    if name is not None and str(name).strip():
        campaign.name = str(name).strip()
        updated_fields.append("name")
    for field in _DATE_FIELDS:
        raw = arguments.get(field)
        if raw is not None and str(raw).strip():
            setattr(campaign, field, _normalize_date(raw))
            updated_fields.append(field)

    if not updated_fields:
        raise ValueError("update_campaign requires at least one of: name, start_date, end_date")

    for path in updated_fields:
        operation.update_mask.paths.append(path)

    request = client.get_type("MutateCampaignsRequest")
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only
    try:
        response = service.mutate_campaigns(request=request)
    except GoogleAdsException as exc:
        raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    payload = {
        "customer_id": customer_id,
        "campaign_id": campaign_id,
        "updated_fields": updated_fields,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

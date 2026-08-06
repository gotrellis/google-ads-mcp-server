"""Tool: remove_negative_keyword — delete a negative keyword criterion.

Removes a negative keyword at the ad-group or campaign level via
``operation.remove`` (the criterion resource name). The level is selected by
which id you pass (exactly one):

    ad_group_id  → AdGroupCriterionService.mutate_ad_group_criteria
    campaign_id  → CampaignCriterionService.mutate_campaign_criteria

``criterion_id`` identifies the negative — read it from ``ad_group_criterion``
(ad-group) or ``campaign_criterion`` (campaign) where ``negative = true``.
``validate_only=true`` performs a dry run (no resource names returned).

Note: negatives are immutable — to "edit" one, remove it here and re-create it
with add_negative_keyword.
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message


TOOL = Tool(
    name="remove_negative_keyword",
    description=(
        "Remove a negative keyword. Pass exactly one of ad_group_id (ad-group "
        "level) or campaign_id (campaign level), plus criterion_id (the negative's "
        "ad_group_criterion.criterion_id / campaign_criterion.criterion_id from a "
        "read where negative=true). Pass validate_only=true for a dry run."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID owning the negative, no dashes (e.g. '1234567890').",
            },
            "ad_group_id": {
                "type": "string",
                "description": "Ad group ID for an ad-group-level negative. Exactly one of ad_group_id / campaign_id.",
            },
            "campaign_id": {
                "type": "string",
                "description": "Campaign ID for a campaign-level negative. Exactly one of ad_group_id / campaign_id.",
            },
            "criterion_id": {
                "type": "string",
                "description": "Criterion ID of the negative to remove (numeric criterion_id from a read).",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate the change without applying it. Default false.",
            },
        },
        "required": ["customer_id", "criterion_id"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    criterion_id = _last_segment(arguments.get("criterion_id", ""))
    validate_only = bool(arguments.get("validate_only", False))

    if not criterion_id:
        raise ValueError("criterion_id is required (the negative keyword's criterion id)")

    raw_ad_group = arguments.get("ad_group_id")
    raw_campaign = arguments.get("campaign_id")
    has_ad_group = raw_ad_group is not None and str(raw_ad_group).strip()
    has_campaign = raw_campaign is not None and str(raw_campaign).strip()
    if bool(has_ad_group) == bool(has_campaign):
        raise ValueError("provide exactly one of ad_group_id (ad-group negative) or campaign_id (campaign negative)")

    ad_group_id = campaign_id = None
    if has_ad_group:
        ad_group_id = _last_segment(raw_ad_group)
        service = client.get_service("AdGroupCriterionService")
        operation = client.get_type("AdGroupCriterionOperation")
        operation.remove = service.ad_group_criterion_path(customer_id, ad_group_id, criterion_id)
        request = client.get_type("MutateAdGroupCriteriaRequest")
        level = "ad_group"
    else:
        campaign_id = _last_segment(raw_campaign)
        service = client.get_service("CampaignCriterionService")
        operation = client.get_type("CampaignCriterionOperation")
        operation.remove = service.campaign_criterion_path(customer_id, campaign_id, criterion_id)
        request = client.get_type("MutateCampaignCriteriaRequest")
        level = "campaign"

    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only
    try:
        if level == "ad_group":
            response = service.mutate_ad_group_criteria(request=request)
        else:
            response = service.mutate_campaign_criteria(request=request)
    except GoogleAdsException as exc:
        raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    payload = {
        "customer_id": customer_id,
        "level": level,
        "ad_group_id": ad_group_id,
        "campaign_id": campaign_id,
        "criterion_id": criterion_id,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

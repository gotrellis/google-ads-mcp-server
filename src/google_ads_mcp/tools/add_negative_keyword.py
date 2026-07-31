"""Tool: add_negative_keyword — block a term at the ad-group or campaign level.

Creates a **negative** keyword criterion so a search term stops triggering ads.
The level is selected by which id you pass (exactly one):

    ad_group_id  → AdGroupCriterionService.mutate_ad_group_criteria (ad-group negative)
    campaign_id  → CampaignCriterionService.mutate_campaign_criteria (campaign-wide negative)

Both create a criterion with ``negative = true`` and a ``keyword`` (text +
match type). ``match_type`` is EXACT / PHRASE / BROAD (default EXACT — blocks
exactly the term; PHRASE/BROAD block progressively more). ``validate_only=true``
performs a dry run (no resource names returned).

The canonical use is negating wasteful search terms: read ``search_term_view``,
filter, then add the terms here.
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message

_ALLOWED_MATCH_TYPES = ("EXACT", "PHRASE", "BROAD")
# Google caps a keyword at 80 characters / 10 words; reject early with a clear message.
_MAX_TEXT_LEN = 80


TOOL = Tool(
    name="add_negative_keyword",
    description=(
        "Add a negative keyword so a term stops triggering Google Ads. Pass "
        "exactly one of ad_group_id (ad-group-level negative, "
        "AdGroupCriterionService) or campaign_id (campaign-wide negative, "
        "CampaignCriterionService). match_type is EXACT / PHRASE / BROAD "
        "(default EXACT). Pass validate_only=true for a dry run. Common use: "
        "negate wasteful terms from a search_term_view read."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID owning the campaign/ad group, no dashes (e.g. '1234567890').",
            },
            "ad_group_id": {
                "type": "string",
                "description": (
                    "Ad group ID for an ad-group-level negative (numeric ad_group.id). "
                    "Provide exactly one of ad_group_id or campaign_id."
                ),
            },
            "campaign_id": {
                "type": "string",
                "description": (
                    "Campaign ID for a campaign-wide negative (numeric campaign.id). "
                    "Provide exactly one of ad_group_id or campaign_id."
                ),
            },
            "text": {
                "type": "string",
                "description": "The negative keyword text (max 80 chars / 10 words).",
            },
            "match_type": {
                "type": "string",
                "enum": list(_ALLOWED_MATCH_TYPES),
                "description": "Negative match type: EXACT (default), PHRASE, or BROAD.",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate the change without applying it. Default false.",
            },
        },
        "required": ["customer_id", "text"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    text = str(arguments.get("text", "")).strip()
    match_type = str(arguments.get("match_type") or "EXACT").strip().upper()
    validate_only = bool(arguments.get("validate_only", False))

    if not text:
        raise ValueError("text is required (the negative keyword)")
    if len(text) > _MAX_TEXT_LEN:
        raise ValueError(f"text exceeds the {_MAX_TEXT_LEN}-char limit for a keyword: {text!r}")
    if match_type not in _ALLOWED_MATCH_TYPES:
        raise ValueError(f"match_type must be one of {list(_ALLOWED_MATCH_TYPES)}, got {arguments.get('match_type')!r}")

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
        criterion = operation.create
        criterion.ad_group = service.ad_group_path(customer_id, ad_group_id)
        level = "ad_group"
    else:
        campaign_id = _last_segment(raw_campaign)
        service = client.get_service("CampaignCriterionService")
        operation = client.get_type("CampaignCriterionOperation")
        criterion = operation.create
        criterion.campaign = service.campaign_path(customer_id, campaign_id)
        level = "campaign"

    # Common to both levels: a negative keyword criterion.
    criterion.negative = True
    criterion.keyword.text = text
    criterion.keyword.match_type = client.enums.KeywordMatchTypeEnum[match_type]

    # validate_only is a field on the request message, not a kwarg of mutate_*().
    if level == "ad_group":
        request = client.get_type("MutateAdGroupCriteriaRequest")
        request.customer_id = customer_id
        request.operations.append(operation)
        request.validate_only = validate_only
        try:
            response = service.mutate_ad_group_criteria(request=request)
        except GoogleAdsException as exc:
            raise RuntimeError(google_ads_error_message(exc)) from exc
    else:
        request = client.get_type("MutateCampaignCriteriaRequest")
        request.customer_id = customer_id
        request.operations.append(operation)
        request.validate_only = validate_only
        try:
            response = service.mutate_campaign_criteria(request=request)
        except GoogleAdsException as exc:
            raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    payload = {
        "customer_id": customer_id,
        "level": level,
        "ad_group_id": ad_group_id,
        "campaign_id": campaign_id,
        "text": text,
        "match_type": match_type,
        "negative": True,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

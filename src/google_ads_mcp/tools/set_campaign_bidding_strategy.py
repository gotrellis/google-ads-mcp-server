"""Tool: set_campaign_bidding_strategy — switch a campaign's standard bidding strategy.

Sets the campaign-level (standard) bidding strategy via
``CampaignService.mutate_campaigns``. The bidding strategy is a ``oneof`` on the
Campaign, so we select the chosen member (via ``copy_from`` of an empty message,
which marks the oneof present) and put its *subfield* paths in the update mask.
The mask must reference subfields (e.g. ``target_spend.cpc_bid_ceiling_micros``),
never the parent message field ``target_spend`` — Google rejects a mask that
points at a message with subfields (``FieldMaskError.FIELD_HAS_SUBFIELDS``).
Masking a subfield of the selected member is what switches the strategy; any
subfield left unset is written as its default (no target / no bid ceiling).

Supported strategies (the modern standard set):

    MANUAL_CPC                 — manual CPC (optional ``enhanced_cpc``)
    MAXIMIZE_CONVERSIONS       — maximize conversions (optional ``target_cpa_micros`` = "Target CPA")
    MAXIMIZE_CONVERSION_VALUE  — maximize conversion value (optional ``target_roas`` = "Target ROAS")
    TARGET_SPEND               — maximize clicks

``validate_only`` performs a dry run — strongly recommended, since a strategy
switch is often rejected on ineligible campaigns (e.g. conversion-based strategies
require conversion tracking); the dry run surfaces that without applying anything.
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message

# strategy name -> (Campaign oneof field, its message type, mutable subfield paths
# for the update mask). The mask must reference these *subfields*, never the parent
# message field: Google rejects a mask path that points at a message that has
# subfields (FieldMaskError.FIELD_HAS_SUBFIELDS). Masking a subfield of the selected
# oneof member is what actually switches the campaign to that strategy.
_STRATEGIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "MANUAL_CPC": ("manual_cpc", "ManualCpc", ("enhanced_cpc_enabled",)),
    "MAXIMIZE_CONVERSIONS": ("maximize_conversions", "MaximizeConversions", ("target_cpa_micros",)),
    "MAXIMIZE_CONVERSION_VALUE": ("maximize_conversion_value", "MaximizeConversionValue", ("target_roas",)),
    "TARGET_SPEND": ("target_spend", "TargetSpend", ("cpc_bid_ceiling_micros",)),
}


TOOL = Tool(
    name="set_campaign_bidding_strategy",
    description=(
        "Switch a Google Ads campaign's standard bidding strategy. bidding_strategy is one of "
        "MANUAL_CPC, MAXIMIZE_CONVERSIONS, MAXIMIZE_CONVERSION_VALUE, TARGET_SPEND (maximize clicks). "
        "Optional targets: target_cpa_micros (Target CPA, MAXIMIZE_CONVERSIONS only), target_roas "
        "(Target ROAS ratio e.g. 4.0, MAXIMIZE_CONVERSION_VALUE only), enhanced_cpc (MANUAL_CPC only). "
        "Pass validate_only=true for a dry run — recommended, as a switch can be rejected on "
        "ineligible campaigns."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "Customer ID owning the campaign, no dashes."},
            "campaign_id": {"type": "string", "description": "Campaign ID to update (numeric campaign.id)."},
            "bidding_strategy": {
                "type": "string",
                "enum": list(_STRATEGIES),
                "description": "The standard bidding strategy to set.",
            },
            "target_cpa_micros": {
                "type": "integer",
                "description": "Target CPA in micros (MAXIMIZE_CONVERSIONS only, optional).",
            },
            "target_roas": {
                "type": "number",
                "description": "Target ROAS as a ratio, e.g. 4.0 = 400% (MAXIMIZE_CONVERSION_VALUE only, optional).",
            },
            "enhanced_cpc": {
                "type": "boolean",
                "description": "Enable Enhanced CPC (MANUAL_CPC only, optional).",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate the change without applying it. Default false.",
            },
        },
        "required": ["customer_id", "campaign_id", "bidding_strategy"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    campaign_id = _last_segment(arguments["campaign_id"])
    strategy = str(arguments["bidding_strategy"]).strip().upper()
    validate_only = bool(arguments.get("validate_only", False))

    if strategy not in _STRATEGIES:
        raise ValueError(f"bidding_strategy must be one of {list(_STRATEGIES)}, got {arguments.get('bidding_strategy')!r}")

    service = client.get_service("CampaignService")
    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = service.campaign_path(customer_id, campaign_id)

    field, type_name, mask_subfields = _STRATEGIES[strategy]
    # Select the oneof by copying an empty message into it — this marks the member
    # present even when no target is set, which is what a bare switch (e.g. maximize
    # clicks) needs.
    client.copy_from(getattr(campaign, field), client.get_type(type_name))
    if strategy == "MANUAL_CPC":
        # eCPC defaults off; set it explicitly so the masked leaf carries a value.
        campaign.manual_cpc.enhanced_cpc_enabled = bool(arguments.get("enhanced_cpc") or False)
    elif strategy == "MAXIMIZE_CONVERSIONS" and arguments.get("target_cpa_micros") is not None:
        campaign.maximize_conversions.target_cpa_micros = int(arguments["target_cpa_micros"])
    elif strategy == "MAXIMIZE_CONVERSION_VALUE" and arguments.get("target_roas") is not None:
        campaign.maximize_conversion_value.target_roas = float(arguments["target_roas"])

    # Mask the strategy's *subfields*, never the parent message field: a mask path
    # that points at a message with subfields is rejected (FIELD_HAS_SUBFIELDS).
    # Masking a subfield of the selected member switches the strategy; a subfield
    # left unset is written as its default (no target CPA/ROAS, no bid ceiling).
    for subfield in mask_subfields:
        operation.update_mask.paths.append(f"{field}.{subfield}")

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
        "bidding_strategy": strategy,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

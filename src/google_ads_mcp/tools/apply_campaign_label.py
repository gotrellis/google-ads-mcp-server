"""Tool: apply_campaign_label — attach a label to a campaign.

Creates a ``CampaignLabel`` link via ``CampaignLabelService.mutate_campaign_labels``
(a create operation — no update mask). The label must already exist; create one
with ``create_label`` (or read an existing ``label.id``). ``validate_only=true``
performs a dry run.
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message


TOOL = Tool(
    name="apply_campaign_label",
    description=(
        "Attach an existing label to a campaign (CampaignLabelService."
        "mutate_campaign_labels). Requires customer_id, campaign_id and label_id "
        "(the label must already exist — see create_label). Pass validate_only=true "
        "for a dry run."
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
                "description": "Campaign ID to label (the numeric campaign.id from a read).",
            },
            "label_id": {
                "type": "string",
                "description": "Label ID to apply (numeric label.id, e.g. from create_label).",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate the change without applying it. Default false.",
            },
        },
        "required": ["customer_id", "campaign_id", "label_id"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    campaign_id = _last_segment(arguments["campaign_id"])
    label_id = _last_segment(arguments["label_id"])
    validate_only = bool(arguments.get("validate_only", False))

    campaign_service = client.get_service("CampaignService")
    label_service = client.get_service("LabelService")
    service = client.get_service("CampaignLabelService")

    operation = client.get_type("CampaignLabelOperation")
    campaign_label = operation.create
    campaign_label.campaign = campaign_service.campaign_path(customer_id, campaign_id)
    campaign_label.label = label_service.label_path(customer_id, label_id)

    request = client.get_type("MutateCampaignLabelsRequest")
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only
    try:
        response = service.mutate_campaign_labels(request=request)
    except GoogleAdsException as exc:
        raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    payload = {
        "customer_id": customer_id,
        "campaign_id": campaign_id,
        "label_id": label_id,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

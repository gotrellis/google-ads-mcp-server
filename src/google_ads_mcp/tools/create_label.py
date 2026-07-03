"""Tool: create_label — create a Label (LabelService.mutate_labels).

Creates an account-level ``Label`` that can then be applied to campaigns (see
``apply_campaign_label``). Only ``name`` is required; ``description`` and
``background_color`` (hex, e.g. ``#FF5733``) populate the label's ``text_label``.

This is a *create* operation, so there is no update mask. ``validate_only=true``
validates without creating and returns no resource name.
"""

from __future__ import annotations

import json
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message


TOOL = Tool(
    name="create_label",
    description=(
        "Create a Google Ads label (LabelService.mutate_labels). Required: name. "
        "Optional: description, background_color (hex like '#FF5733'). Returns the "
        "new label's resource name and id — use that label_id with "
        "apply_campaign_label. Pass validate_only=true for a dry run."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID that will own the label, no dashes (e.g. '1234567890').",
            },
            "name": {"type": "string", "description": "Label name (must be unique in the account)."},
            "description": {"type": "string", "description": "Optional label description."},
            "background_color": {
                "type": "string",
                "description": "Optional background color as a hex string, e.g. '#FF5733'.",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate without creating. Default false.",
            },
        },
        "required": ["customer_id", "name"],
    },
)


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    name = str(arguments["name"]).strip()
    if not name:
        raise ValueError("name is required and cannot be blank")
    validate_only = bool(arguments.get("validate_only", False))

    service = client.get_service("LabelService")
    operation = client.get_type("LabelOperation")
    label = operation.create
    label.name = name

    description = arguments.get("description")
    if description is not None and str(description).strip():
        label.text_label.description = str(description).strip()
    background_color = arguments.get("background_color")
    if background_color is not None and str(background_color).strip():
        label.text_label.background_color = str(background_color).strip()

    request = client.get_type("MutateLabelsRequest")
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only
    try:
        response = service.mutate_labels(request=request)
    except GoogleAdsException as exc:
        raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    label_resource_name = results[0] if results else None
    label_id = label_resource_name.rstrip("/").split("/")[-1] if label_resource_name else None
    payload = {
        "customer_id": customer_id,
        "name": name,
        "label_resource_name": label_resource_name,
        "label_id": label_id,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

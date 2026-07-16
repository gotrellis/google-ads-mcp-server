"""Tool: update_campaign_budget — change a campaign budget's amount.

Updates ``campaign_budget.amount_micros`` via
``CampaignBudgetService.mutate_campaign_budgets`` with an update mask covering
only ``amount_micros``.

The budget is the shared ``CampaignBudget`` entity — NOT the campaign — so the
id comes from an upstream read of ``campaign.campaign_budget`` (a resource name
whose trailing segment is the budget id; a full resource name is also accepted).
A budget can be shared by several campaigns, so changing it affects all of them.

``amount_micros`` is in micros of the account currency ($25.00 = 25_000_000).
``validate_only=true`` performs a dry run (no resource names returned).
"""

from __future__ import annotations

import json
import os
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from mcp.types import TextContent, Tool

from ._errors import google_ads_error_message

# Defense-in-depth backstop against an absurd / injected budget reaching a live account.
# The parent (clio-idx) enforces the real, tighter ceiling; this only rejects clearly
# out-of-range values on any path (incl. a direct chat-agent call). Override via
# GOOGLE_ADS_MAX_BUDGET_MICROS (micros); default 10_000_000_000_000 (~$10M/day).
_DEFAULT_MAX_BUDGET_MICROS = 10_000_000_000_000


def _max_budget_micros() -> int:
    """Upper bound for amount_micros: env ``GOOGLE_ADS_MAX_BUDGET_MICROS`` else the default."""
    try:
        value = int(os.environ.get("GOOGLE_ADS_MAX_BUDGET_MICROS", ""))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_BUDGET_MICROS
    return value if value > 0 else _DEFAULT_MAX_BUDGET_MICROS


TOOL = Tool(
    name="update_campaign_budget",
    description=(
        "Update the amount of a Google Ads campaign budget (the shared "
        "CampaignBudget entity, not the campaign). Sets amount_micros via "
        "CampaignBudgetService.mutate_campaign_budgets (update_mask on "
        "amount_micros only). amount_micros is the budget in micros of the "
        "account currency ($25.00 = 25000000). Note: a budget can be shared by "
        "several campaigns; changing it affects all of them. Pass "
        "validate_only=true for a dry run."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID owning the budget, no dashes (e.g. '1234567890').",
            },
            "campaign_budget_id": {
                "type": "string",
                "description": (
                    "CampaignBudget ID — the trailing segment of a campaign.campaign_budget "
                    "resource name ('customers/{cid}/campaignBudgets/{id}'). A full resource "
                    "name is also accepted."
                ),
            },
            "amount_micros": {
                "type": "integer",
                "description": "New budget amount in micros (account currency * 1,000,000).",
            },
            "validate_only": {
                "type": "boolean",
                "description": "If true, validate the change without applying it. Default false.",
            },
        },
        "required": ["customer_id", "campaign_budget_id", "amount_micros"],
    },
)


def _last_segment(value: Any) -> str:
    """Accept either a bare id or a full resource name; return the trailing id."""
    return str(value).rstrip("/").split("/")[-1]


def call(client: Any, arguments: dict[str, Any]) -> list[TextContent]:
    customer_id = str(arguments["customer_id"]).replace("-", "")
    budget_id = _last_segment(arguments["campaign_budget_id"])
    try:
        amount_micros = int(arguments["amount_micros"])
    except (TypeError, ValueError):
        raise ValueError(f"amount_micros must be an integer, got {arguments.get('amount_micros')!r}") from None
    validate_only = bool(arguments.get("validate_only", False))

    if amount_micros < 0:
        raise ValueError(f"amount_micros must be >= 0, got {amount_micros}")
    max_micros = _max_budget_micros()
    if amount_micros > max_micros:
        raise ValueError(
            f"amount_micros {amount_micros} exceeds the safety ceiling {max_micros} "
            f"(~{max_micros // 1_000_000:,} in account currency). Set GOOGLE_ADS_MAX_BUDGET_MICROS to raise it."
        )

    service = client.get_service("CampaignBudgetService")
    operation = client.get_type("CampaignBudgetOperation")
    budget = operation.update
    budget.resource_name = service.campaign_budget_path(customer_id, budget_id)
    budget.amount_micros = amount_micros
    operation.update_mask.paths.append("amount_micros")

    # validate_only is a field on the request message, NOT a kwarg of
    # mutate_campaign_budgets() — build the request explicitly.
    request = client.get_type("MutateCampaignBudgetsRequest")
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only
    try:
        response = service.mutate_campaign_budgets(request=request)
    except GoogleAdsException as exc:
        raise RuntimeError(google_ads_error_message(exc)) from exc

    results = [r.resource_name for r in response.results]
    payload = {
        "customer_id": customer_id,
        "campaign_budget_id": budget_id,
        "amount_micros": amount_micros,
        "validate_only": validate_only,
        "results": results,
        "mutated": (not validate_only) and bool(results),
    }
    return [TextContent(type="text", text=json.dumps(payload))]

"""Tool: list_accessible_customers.

Returns the list of customer resource names the authenticated user has
access to. Useful as the first call after OAuth — the parent process
typically needs this to populate an account picker, or to validate that
the refresh token is still valid.

Maps to the Google Ads API's ``CustomerService.ListAccessibleCustomers``
which requires only OAuth + developer token (no login_customer_id).
"""

from __future__ import annotations

from typing import Any

from google.ads.googleads.client import GoogleAdsClient
from mcp.types import TextContent, Tool

TOOL = Tool(
    name="list_accessible_customers",
    description=(
        "List the Google Ads customer accounts the authenticated user can "
        "access. Returns resource names of the form 'customers/{customer_id}'. "
        "No arguments. Useful as a first call to verify the OAuth token is "
        "valid and to discover available customer IDs for subsequent tools."
    ),
    inputSchema={
        "type": "object",
        "properties": {},
        "required": [],
    },
)


def call(client: GoogleAdsClient, _arguments: dict[str, Any]) -> list[TextContent]:
    """Invoke CustomerService.list_accessible_customers."""
    service = client.get_service("CustomerService")
    response = service.list_accessible_customers()

    resource_names = list(response.resource_names)
    # Strip the prefix so consumers can pass the bare ID to subsequent tools
    # — saves a string-split in the caller and matches the format the rest of
    # the API expects in ``customer_id`` parameters.
    customer_ids = [name.split("/", 1)[-1] for name in resource_names]

    payload = {
        "resource_names": resource_names,
        "customer_ids": customer_ids,
    }
    import json

    return [TextContent(type="text", text=json.dumps(payload))]

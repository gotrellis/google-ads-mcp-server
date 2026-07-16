"""Tool modules exposed by the MCP server.

Each tool module exports ``TOOL`` (an ``mcp.types.Tool``) and
``call(client, arguments) -> list[TextContent]``. ``server.py`` wires them up
by listing them in ``TOOL_MODULES``; they are imported here too so the package
surfaces every tool in one place. (``_errors`` is a shared helper, not a tool.)
"""

from . import (
    apply_campaign_label,
    create_label,
    gaql_search,
    list_customers,
    remove_campaign_label,
    search,
    set_campaign_bidding_strategy,
    set_campaign_status,
    update_ad_group,
    update_ad_group_ad,
    update_ad_group_criterion,
    update_campaign,
    update_campaign_budget,
)

__all__ = [
    "apply_campaign_label",
    "create_label",
    "gaql_search",
    "list_customers",
    "remove_campaign_label",
    "search",
    "set_campaign_bidding_strategy",
    "set_campaign_status",
    "update_ad_group",
    "update_ad_group_ad",
    "update_ad_group_criterion",
    "update_campaign",
    "update_campaign_budget",
]

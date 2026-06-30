"""Tool modules exposed by the MCP server.

Each tool module exports ``TOOL`` (an ``mcp.types.Tool``) and
``call(client, arguments) -> list[TextContent]``. ``server.py`` wires them up
by listing them in ``TOOL_MODULES``; they are imported here too so the package
surfaces every tool in one place. (``_errors`` is a shared helper, not a tool.)
"""

from . import (
    gaql_search,
    list_customers,
    search,
    set_campaign_status,
    update_campaign_budget,
)

__all__ = [
    "gaql_search",
    "list_customers",
    "search",
    "set_campaign_status",
    "update_campaign_budget",
]

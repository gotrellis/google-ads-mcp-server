"""Google Ads MCP server — stdio transport.

Hosts an ``mcp.server.Server`` over stdio. The parent process
(clio-idx) spawns this binary as a subprocess and communicates over the
MCP protocol on stdin/stdout — that's why all logging goes to stderr.

Tool registration is centralized here so adding a new tool only requires:

1. Drop a module in ``tools/`` exporting ``TOOL`` (an ``mcp.types.Tool``)
   and ``call(client, arguments) -> list[TextContent]``.
2. Add it to ``TOOL_MODULES`` below.

The single ``GoogleAdsClient`` instance is built lazily on the first tool
call. Build errors surface as a tool-call error rather than a startup
crash so the parent can still see ``list_tools`` succeed (which the LLM
needs to know what's available).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from .client import build_client
from .config import load_config
from .tools import (
    add_negative_keyword,
    apply_campaign_label,
    create_label,
    gaql_search,
    list_customers,
    remove_campaign_label,
    remove_negative_keyword,
    search,
    set_campaign_bidding_strategy,
    set_campaign_status,
    update_ad_group,
    update_ad_group_ad,
    update_ad_group_criterion,
    update_campaign,
    update_campaign_budget,
)

# stderr-only — stdout is the MCP transport, polluting it breaks the protocol.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("google_ads_mcp")


SERVER_NAME = "google-ads-mcp"
SERVER_VERSION = "0.1.0"

TOOL_MODULES = [
    # Reads
    list_customers,
    search,
    gaql_search,
    # Writes — campaigns
    set_campaign_status,
    update_campaign_budget,
    set_campaign_bidding_strategy,
    update_campaign,
    create_label,
    apply_campaign_label,
    remove_campaign_label,
    # Writes — ad groups / ads / keywords
    update_ad_group,
    update_ad_group_ad,
    update_ad_group_criterion,
    add_negative_keyword,
    remove_negative_keyword,
]


def _build_server() -> Server:
    # Lazy client — first tool call builds it. Lets list_tools succeed even
    # if env-var config is bad, so the LLM gets a clear "Google Ads tools
    # are available" signal before any auth issue surfaces.
    state: dict[str, Any] = {"client": None}

    def _get_client():
        if state["client"] is None:
            config = load_config()
            state["client"] = build_client(config)
        return state["client"]

    def _dispatch(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # Dispatch by tool name — keep this body small; per-tool logic lives in
        # the tool module's ``call`` so each tool stays independently testable.
        # Failures raise; ``on_call_tool`` below turns them into an error
        # result. Config errors raise too: their message is already actionable,
        # and list_tools still succeeds because the client is built lazily
        # (not during listing).
        for mod in TOOL_MODULES:
            if mod.TOOL.name == name:
                client = _get_client()
                return mod.call(client, arguments)
        raise ValueError(f"Unknown tool: {name!r}")

    async def on_list_tools(ctx: Any, params: Any) -> ListToolsResult:
        return ListToolsResult(tools=[mod.TOOL for mod in TOOL_MODULES])

    async def on_call_tool(ctx: Any, params: Any) -> CallToolResult:
        # A failure MUST come back as isError=True carrying the message: that
        # is how the parent (clio-idx) tells a failed call from a successful
        # one. Returning a {"error": ...} payload with isError unset would be
        # read as a *success*, so e.g. a failed search would silently parse as
        # one junk row.
        #
        # Under mcp 1.x the SDK did this conversion itself, wrapping whatever
        # the handler raised. 2.x does not: an exception that escapes here
        # becomes a JSON-RPC INTERNAL_ERROR whose message is deliberately
        # replaced with a generic string so handler internals never reach the
        # wire — which would strip exactly the detail the parent surfaces to
        # the model. So catch and convert explicitly.
        try:
            return CallToolResult(content=_dispatch(params.name, params.arguments or {}))
        except Exception as exc:
            logger.exception("tool %s failed", params.name)
            # Some exceptions stringify empty (a bare KeyError()), and a blank
            # error message tells the model nothing.
            text = str(exc) or type(exc).__name__
            return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)

    return Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def _serve() -> None:
    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        # Capabilities are derived from the handlers actually registered rather
        # than hand-built, so the server can never advertise something it has
        # no handler for.
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run() -> None:
    """Entry point declared in ``pyproject.toml``'s ``[project.scripts]``."""
    asyncio.run(_serve())


if __name__ == "__main__":
    run()

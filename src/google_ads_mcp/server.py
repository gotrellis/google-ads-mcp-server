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
import json
import logging
import sys
from typing import Any

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import ServerCapabilities, TextContent, Tool, ToolsCapability

from .client import build_client
from .config import ConfigError, load_config
from .tools import gaql_search, list_customers

# stderr-only — stdout is the MCP transport, polluting it breaks the protocol.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("google_ads_mcp")


TOOL_MODULES = [list_customers, gaql_search]


def _build_server() -> Server:
    server: Server = Server("google-ads-mcp")

    # Lazy client — first tool call builds it. Lets list_tools succeed even
    # if env-var config is bad, so the LLM gets a clear "Google Ads tools
    # are available" signal before any auth issue surfaces.
    state: dict[str, Any] = {"client": None}

    def _get_client():
        if state["client"] is None:
            config = load_config()
            state["client"] = build_client(config)
        return state["client"]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [mod.TOOL for mod in TOOL_MODULES]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # Dispatch by tool name — keep this body small; per-tool logic lives
        # in the tool module's ``call`` so each tool stays independently
        # testable.
        for mod in TOOL_MODULES:
            if mod.TOOL.name == name:
                try:
                    client = _get_client()
                    return mod.call(client, arguments)
                except ConfigError as e:
                    # Surface env-var problems as a tool-call error so the LLM
                    # (and the parent's error UI) sees the actionable message
                    # instead of a generic transport-level crash.
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps({"error": str(e), "error_type": "ConfigError"}),
                        )
                    ]
                except Exception as e:  # noqa: BLE001 — surface anything the API throws
                    logger.exception("tool %s failed", name)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {"error": str(e), "error_type": type(e).__name__}
                            ),
                        )
                    ]
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name!r}"}),
            )
        ]

    return server


async def _serve() -> None:
    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="google-ads-mcp",
                server_version="0.1.0",
                capabilities=ServerCapabilities(tools=ToolsCapability(listChanged=False)),
            ),
        )


def run() -> None:
    """Entry point declared in ``pyproject.toml``'s ``[project.scripts]``."""
    asyncio.run(_serve())


if __name__ == "__main__":
    run()

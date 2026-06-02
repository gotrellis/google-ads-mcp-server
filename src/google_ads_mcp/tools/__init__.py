"""Tool registrations exposed by the MCP server.

Each tool module defines its own ``register(server)`` function that
attaches handlers to the ``mcp.server.Server`` instance. Add new tool
modules by importing them here and calling their ``register``.
"""

from . import gaql_search, list_customers

__all__ = ["gaql_search", "list_customers"]

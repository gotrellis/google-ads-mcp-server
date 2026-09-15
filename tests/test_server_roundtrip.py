"""End-to-end MCP round trips against the server, over real stdio.

The rest of the suite checks the pieces; this drives the server the way
clio-idx does -- spawn it as a subprocess, speak MCP over its stdin/stdout --
which is the whole of the contract between them. clio-idx installs this
package into its own virtualenv and only ever execs the console script, so a
break in the wiring (registration, entry point, startup) shows up here and
nowhere else in the suite.

Neither test needs Google Ads credentials: ``list_tools`` is answered from the
static tool table, and the error case is rejected by name before the lazy
client is built.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _server_params() -> StdioServerParameters:
    env = dict(os.environ)
    # The subprocess is a fresh interpreter: point it at the checkout rather
    # than requiring an editable install for the suite to run.
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "google_ads_mcp.server"],
        env=env,
    )


class StdioRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_tools_returns_the_registered_tools(self):
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()

        names = {tool.name for tool in result.tools}
        self.assertIn("search", names)
        self.assertIn("list_accessible_customers", names)

    async def test_a_failing_tool_call_is_flagged_and_keeps_its_message(self):
        """The contract clio-idx reads: isError=True, with a usable message.

        Under mcp 2.x nothing converts a raised exception for us — an escaped
        exception reaches the wire as a generic "Internal server error" with
        the real message stripped. ``on_call_tool`` catches and builds the
        error result by hand, and this is the test that holds it to that: if it
        regresses, the parent can no longer tell a failed tool call from a
        successful one and a failed search parses as one junk row.
        """
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("no_such_tool", {})

        self.assertTrue(result.is_error, "a failed tool call must set isError")
        self.assertIn("no_such_tool", result.content[0].text)


if __name__ == "__main__":
    unittest.main()

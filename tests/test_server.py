"""Tests for server wiring.

Run with: ``uv run python -m unittest discover -s tests``

The tool modules were already covered, but nothing exercised ``_build_server``
itself — so an incompatible ``mcp`` release could remove the decorator API the
server is written against and every test would still pass while the server
failed to start. ``BuildServerTests`` closes that gap.
"""

from __future__ import annotations

import unittest

from google_ads_mcp.server import TOOL_MODULES, _build_server


class BuildServerTests(unittest.TestCase):
    def test_build_server_succeeds(self):
        """Registers the list_tools/call_tool handlers against the installed mcp SDK."""
        server = _build_server()
        self.assertIsNotNone(server)

    def test_build_server_is_repeatable(self):
        self.assertIsNot(_build_server(), _build_server())


class ToolRegistryTests(unittest.TestCase):
    def test_every_module_exposes_the_tool_contract(self):
        for mod in TOOL_MODULES:
            with self.subTest(module=mod.__name__):
                self.assertTrue(hasattr(mod, "TOOL"), "missing TOOL")
                self.assertTrue(callable(getattr(mod, "call", None)), "missing call()")

    def test_tool_names_are_unique(self):
        names = [mod.TOOL.name for mod in TOOL_MODULES]
        self.assertEqual(len(names), len(set(names)), f"duplicate tool name in {names}")

    def test_every_tool_has_a_description_and_object_schema(self):
        for mod in TOOL_MODULES:
            with self.subTest(tool=mod.TOOL.name):
                self.assertTrue(mod.TOOL.description)
                self.assertEqual(mod.TOOL.inputSchema.get("type"), "object")

    def test_required_fields_are_declared_in_properties(self):
        for mod in TOOL_MODULES:
            schema = mod.TOOL.inputSchema
            properties = schema.get("properties", {})
            for field in schema.get("required", []):
                with self.subTest(tool=mod.TOOL.name, field=field):
                    self.assertIn(field, properties)

    def test_the_documented_tools_are_all_registered(self):
        names = {mod.TOOL.name for mod in TOOL_MODULES}
        expected = {
            "list_accessible_customers",
            "search",
            "gaql_search",
            "set_campaign_status",
            "update_campaign_budget",
            "set_campaign_bidding_strategy",
            "update_campaign",
            "create_label",
            "apply_campaign_label",
            "remove_campaign_label",
            "update_ad_group",
            "update_ad_group_ad",
            "update_ad_group_criterion",
            "add_negative_keyword",
            "remove_negative_keyword",
        }
        self.assertEqual(expected - names, set(), "tool missing from TOOL_MODULES")


if __name__ == "__main__":
    unittest.main()

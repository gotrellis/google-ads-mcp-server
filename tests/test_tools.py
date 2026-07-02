"""Tests for the read/write tool modules.

Run with: ``uv run python -m unittest discover -s tests``
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from google_ads_mcp.tools import search, set_campaign_status, update_campaign_budget
from google_ads_mcp.tools._errors import google_ads_error_message


def _payload(result):
    """Extract and parse the JSON payload from a tool's TextContent result."""
    assert len(result) == 1, result
    return json.loads(result[0].text)


# ── search: query building + value formatting (pure, no SDK) ──────────────────


class BuildQueryTests(unittest.TestCase):
    def test_minimal_query(self):
        q = search._build_query(["campaign.id", "campaign.name"], "campaign")
        self.assertEqual(q, "SELECT campaign.id,campaign.name FROM campaign")

    def test_full_query(self):
        q = search._build_query(
            ["campaign.id", "metrics.clicks"],
            "campaign",
            conditions=["campaign.status = 'ENABLED'", "metrics.clicks > 0"],
            orderings=["metrics.clicks DESC"],
            limit=10,
        )
        self.assertEqual(
            q,
            "SELECT campaign.id,metrics.clicks FROM campaign"
            " WHERE campaign.status = 'ENABLED' AND metrics.clicks > 0"
            " ORDER BY metrics.clicks DESC"
            " LIMIT 10",
        )

    def test_empty_clauses_are_omitted(self):
        q = search._build_query(["campaign.id"], "campaign", conditions=[], orderings=[], limit=None)
        self.assertNotIn("WHERE", q)
        self.assertNotIn("ORDER BY", q)
        self.assertNotIn("LIMIT", q)

    def test_no_omit_unselected_resource_names(self):
        # This parameter must NOT be present — it drops id / resource-name fields
        # (campaign.id, campaign.campaign_budget) from the response field_mask.
        q = search._build_query(["campaign.id"], "campaign")
        self.assertNotIn("omit_unselected_resource_names", q)


class FormatRowTests(unittest.TestCase):
    def test_extracts_requested_nested_fields(self):
        # _format_row reads exactly the requested dotted paths off the row — including
        # the nested id / resource-name fields (customer.id, campaign.id,
        # campaign.campaign_budget) that the API's field_mask omits.
        row = SimpleNamespace(
            customer=SimpleNamespace(id=123),
            campaign=SimpleNamespace(
                id=55, name="Summer", campaign_budget="customers/123/campaignBudgets/9"
            ),
        )
        out = search._format_row(
            row, ["customer.id", "campaign.id", "campaign.name", "campaign.campaign_budget"]
        )
        self.assertEqual(
            out,
            {
                "customer.id": 123,
                "campaign.id": 55,
                "campaign.name": "Summer",
                "campaign.campaign_budget": "customers/123/campaignBudgets/9",
            },
        )


class FormatValueTests(unittest.TestCase):
    def test_scalar_passthrough(self):
        self.assertEqual(search._format_value(5), 5)
        self.assertEqual(search._format_value("x"), "x")

    def test_string_not_treated_as_iterable(self):
        self.assertEqual(search._format_value("abc"), "abc")

    def test_list_of_scalars(self):
        self.assertEqual(search._format_value([1, 2, 3]), [1, 2, 3])


# ── set_campaign_status ───────────────────────────────────────────────────────


class SetCampaignStatusTests(unittest.TestCase):
    def _client(self, result_name="customers/123/campaigns/55"):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.campaign_path.return_value = result_name
        service.mutate_campaigns.return_value.results = [SimpleNamespace(resource_name=result_name)]
        operation = mock.MagicMock(name="CampaignOperation")
        request = mock.MagicMock(name="MutateCampaignsRequest")
        client.get_type.side_effect = lambda t: {
            "CampaignOperation": operation,
            "MutateCampaignsRequest": request,
        }[t]
        return client, service, operation, request

    def test_pause_sets_status_mask_and_calls_mutate(self):
        client, service, operation, request = self._client()
        result = set_campaign_status.call(client, {"customer_id": "123", "campaign_id": "55", "status": "PAUSED"})

        client.get_service.assert_called_with("CampaignService")
        service.campaign_path.assert_called_once_with("123", "55")
        self.assertEqual(operation.update.resource_name, "customers/123/campaigns/55")
        client.enums.CampaignStatusEnum.__getitem__.assert_called_once_with("PAUSED")
        self.assertEqual(operation.update.status, client.enums.CampaignStatusEnum.__getitem__.return_value)
        operation.update_mask.paths.append.assert_called_once_with("status")

        # validate_only lives on the request message; mutate is called with request=.
        self.assertEqual(request.customer_id, "123")
        request.operations.append.assert_called_once_with(operation)
        self.assertFalse(request.validate_only)
        service.mutate_campaigns.assert_called_once_with(request=request)

        payload = _payload(result)
        self.assertEqual(payload["status"], "PAUSED")
        self.assertEqual(payload["results"], ["customers/123/campaigns/55"])
        self.assertTrue(payload["mutated"])

    def test_validate_only_sets_request_flag(self):
        client, service, _operation, request = self._client()
        service.mutate_campaigns.return_value.results = []  # validate_only returns no results
        result = set_campaign_status.call(
            client,
            {"customer_id": "123", "campaign_id": "55", "status": "ENABLED", "validate_only": True},
        )
        self.assertTrue(request.validate_only)
        service.mutate_campaigns.assert_called_once_with(request=request)
        payload = _payload(result)
        self.assertTrue(payload["validate_only"])
        self.assertFalse(payload["mutated"])

    def test_status_is_normalized_uppercase(self):
        client, *_ = self._client()
        set_campaign_status.call(client, {"customer_id": "123", "campaign_id": "55", "status": "paused"})
        client.enums.CampaignStatusEnum.__getitem__.assert_called_once_with("PAUSED")

    def test_dashes_stripped_from_customer_id(self):
        client, service, *_ = self._client()
        set_campaign_status.call(client, {"customer_id": "123-456-7890", "campaign_id": "55", "status": "PAUSED"})
        service.campaign_path.assert_called_once_with("1234567890", "55")

    def test_campaign_id_accepts_resource_name(self):
        client, service, *_ = self._client()
        set_campaign_status.call(
            client,
            {"customer_id": "123", "campaign_id": "customers/123/campaigns/55", "status": "PAUSED"},
        )
        service.campaign_path.assert_called_once_with("123", "55")

    def test_invalid_status_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            set_campaign_status.call(client, {"customer_id": "123", "campaign_id": "55", "status": "REMOVED"})


# ── update_campaign_budget ────────────────────────────────────────────────────


class UpdateCampaignBudgetTests(unittest.TestCase):
    def _client(self, result_name="customers/123/campaignBudgets/77"):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.campaign_budget_path.return_value = result_name
        service.mutate_campaign_budgets.return_value.results = [SimpleNamespace(resource_name=result_name)]
        operation = mock.MagicMock(name="CampaignBudgetOperation")
        request = mock.MagicMock(name="MutateCampaignBudgetsRequest")
        client.get_type.side_effect = lambda t: {
            "CampaignBudgetOperation": operation,
            "MutateCampaignBudgetsRequest": request,
        }[t]
        return client, service, operation, request

    def test_updates_amount_mask_and_calls_mutate(self):
        client, service, operation, request = self._client()
        result = update_campaign_budget.call(
            client, {"customer_id": "123", "campaign_budget_id": "77", "amount_micros": 25000000}
        )

        client.get_service.assert_called_with("CampaignBudgetService")
        service.campaign_budget_path.assert_called_once_with("123", "77")
        self.assertEqual(operation.update.amount_micros, 25000000)
        operation.update_mask.paths.append.assert_called_once_with("amount_micros")

        self.assertEqual(request.customer_id, "123")
        request.operations.append.assert_called_once_with(operation)
        self.assertFalse(request.validate_only)
        service.mutate_campaign_budgets.assert_called_once_with(request=request)

        payload = _payload(result)
        self.assertEqual(payload["amount_micros"], 25000000)
        self.assertEqual(payload["campaign_budget_id"], "77")
        self.assertTrue(payload["mutated"])

    def test_budget_id_extracted_from_resource_name(self):
        client, service, *_ = self._client()
        update_campaign_budget.call(
            client,
            {
                "customer_id": "123",
                "campaign_budget_id": "customers/123/campaignBudgets/77",
                "amount_micros": 1000000,
            },
        )
        service.campaign_budget_path.assert_called_once_with("123", "77")

    def test_amount_string_is_coerced_to_int(self):
        client, *_ = self._client()
        result = update_campaign_budget.call(
            client, {"customer_id": "123", "campaign_budget_id": "77", "amount_micros": "5000000"}
        )
        self.assertEqual(_payload(result)["amount_micros"], 5000000)

    def test_negative_amount_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_campaign_budget.call(
                client, {"customer_id": "123", "campaign_budget_id": "77", "amount_micros": -1}
            )

    def test_non_numeric_amount_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_campaign_budget.call(
                client, {"customer_id": "123", "campaign_budget_id": "77", "amount_micros": "lots"}
            )

    def test_validate_only_dry_run(self):
        client, service, _operation, request = self._client()
        service.mutate_campaign_budgets.return_value.results = []
        result = update_campaign_budget.call(
            client,
            {
                "customer_id": "123",
                "campaign_budget_id": "77",
                "amount_micros": 5000000,
                "validate_only": True,
            },
        )
        self.assertTrue(request.validate_only)
        self.assertFalse(_payload(result)["mutated"])


# ── error formatting ──────────────────────────────────────────────────────────


class ErrorMessageTests(unittest.TestCase):
    def test_collapses_failure_errors_with_request_id(self):
        exc = SimpleNamespace(
            failure=SimpleNamespace(
                errors=[SimpleNamespace(message="Too low."), SimpleNamespace(message="Bad resource.")]
            ),
            request_id="req-1",
        )
        msg = google_ads_error_message(exc)
        self.assertIn("Too low.", msg)
        self.assertIn("Bad resource.", msg)
        self.assertIn("req-1", msg)

    def test_falls_back_to_str_when_no_messages(self):
        exc = SimpleNamespace(failure=SimpleNamespace(errors=[]), request_id=None)
        self.assertIn("Google Ads API error", google_ads_error_message(exc))


if __name__ == "__main__":
    unittest.main()

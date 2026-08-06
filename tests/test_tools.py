"""Tests for the read/write tool modules.

Run with: ``uv run python -m unittest discover -s tests``
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from google_ads_mcp.tools import (
    add_negative_keyword,
    apply_campaign_label,
    create_label,
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

    def test_amount_over_ceiling_raises(self):
        # ~$100M/day is far above the default backstop (~$10M) → rejected before the API.
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_campaign_budget.call(
                client, {"customer_id": "123", "campaign_budget_id": "77", "amount_micros": 99_999_999_999_999}
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


# ── set_campaign_bidding_strategy ─────────────────────────────────────────────


class BiddingStrategyTests(unittest.TestCase):
    def _client(self):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.campaign_path.return_value = "customers/123/campaigns/55"
        service.mutate_campaigns.return_value.results = [SimpleNamespace(resource_name="customers/123/campaigns/55")]
        operation = mock.MagicMock(name="CampaignOperation")
        request = mock.MagicMock(name="MutateCampaignsRequest")

        def get_type(type_name):
            return {"CampaignOperation": operation, "MutateCampaignsRequest": request}.get(
                type_name, mock.MagicMock(name=type_name)
            )

        client.get_type.side_effect = get_type
        return client, service, operation, request

    def test_maximize_conversions_with_target_cpa(self):
        client, service, operation, request = self._client()
        result = set_campaign_bidding_strategy.call(
            client,
            {
                "customer_id": "123",
                "campaign_id": "55",
                "bidding_strategy": "MAXIMIZE_CONVERSIONS",
                "target_cpa_micros": 50_000_000,
            },
        )
        self.assertEqual(operation.update.maximize_conversions.target_cpa_micros, 50_000_000)
        operation.update_mask.paths.append.assert_called_once_with("maximize_conversions.target_cpa_micros")
        request.operations.append.assert_called_once_with(operation)
        service.mutate_campaigns.assert_called_once_with(request=request)
        payload = _payload(result)
        self.assertEqual(payload["bidding_strategy"], "MAXIMIZE_CONVERSIONS")
        self.assertTrue(payload["mutated"])

    def test_maximize_conversion_value_with_target_roas(self):
        client, _service, operation, _request = self._client()
        set_campaign_bidding_strategy.call(
            client,
            {
                "customer_id": "123",
                "campaign_id": "55",
                "bidding_strategy": "MAXIMIZE_CONVERSION_VALUE",
                "target_roas": 4.0,
            },
        )
        self.assertEqual(operation.update.maximize_conversion_value.target_roas, 4.0)
        operation.update_mask.paths.append.assert_called_once_with("maximize_conversion_value.target_roas")

    def test_manual_cpc_enhanced(self):
        client, _service, operation, _request = self._client()
        set_campaign_bidding_strategy.call(
            client,
            {"customer_id": "123", "campaign_id": "55", "bidding_strategy": "MANUAL_CPC", "enhanced_cpc": True},
        )
        self.assertTrue(operation.update.manual_cpc.enhanced_cpc_enabled)
        operation.update_mask.paths.append.assert_called_once_with("manual_cpc.enhanced_cpc_enabled")

    def test_target_spend_maximize_clicks(self):
        client, _service, operation, _request = self._client()
        set_campaign_bidding_strategy.call(
            client, {"customer_id": "123", "campaign_id": "55", "bidding_strategy": "TARGET_SPEND"}
        )
        operation.update_mask.paths.append.assert_called_once_with("target_spend.cpc_bid_ceiling_micros")

    def test_invalid_strategy_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            set_campaign_bidding_strategy.call(
                client, {"customer_id": "123", "campaign_id": "55", "bidding_strategy": "MAGIC"}
            )

    def test_validate_only_dry_run(self):
        client, service, _operation, request = self._client()
        service.mutate_campaigns.return_value.results = []
        result = set_campaign_bidding_strategy.call(
            client,
            {
                "customer_id": "123",
                "campaign_id": "55",
                "bidding_strategy": "TARGET_SPEND",
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


class UpdateCampaignTests(unittest.TestCase):
    def _client(self):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.campaign_path.return_value = "customers/123/campaigns/55"
        service.mutate_campaigns.return_value.results = [SimpleNamespace(resource_name="customers/123/campaigns/55")]
        operation = mock.MagicMock(name="CampaignOperation")
        request = mock.MagicMock(name="MutateCampaignsRequest")

        def get_type(type_name):
            return {"CampaignOperation": operation, "MutateCampaignsRequest": request}.get(
                type_name, mock.MagicMock(name=type_name)
            )

        client.get_type.side_effect = get_type
        return client, service, operation, request

    def test_rename_sets_name_and_mask(self):
        client, service, operation, request = self._client()
        result = update_campaign.call(client, {"customer_id": "123", "campaign_id": "55", "name": "New Name"})
        self.assertEqual(operation.update.name, "New Name")
        operation.update_mask.paths.append.assert_called_once_with("name")
        service.mutate_campaigns.assert_called_once_with(request=request)
        payload = _payload(result)
        self.assertEqual(payload["updated_fields"], ["name"])
        self.assertTrue(payload["mutated"])

    def test_dates_normalized_and_masked(self):
        client, _service, operation, _request = self._client()
        update_campaign.call(
            client,
            {"customer_id": "123", "campaign_id": "55", "start_date": "20260801", "end_date": "2026-09-30"},
        )
        # YYYYMMDD is normalized to the extended form; already-extended passes through.
        self.assertEqual(operation.update.start_date, "2026-08-01")
        self.assertEqual(operation.update.end_date, "2026-09-30")
        self.assertEqual(operation.update_mask.paths.append.call_count, 2)

    def test_requires_at_least_one_editable_field(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_campaign.call(client, {"customer_id": "123", "campaign_id": "55"})

    def test_malformed_date_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_campaign.call(client, {"customer_id": "123", "campaign_id": "55", "start_date": "Aug 1"})

    def test_impossible_calendar_date_raises(self):
        # Shape-valid but not a real date must raise before the API call.
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_campaign.call(client, {"customer_id": "123", "campaign_id": "55", "start_date": "2026-13-45"})
        with self.assertRaises(ValueError):
            update_campaign.call(client, {"customer_id": "123", "campaign_id": "55", "end_date": "20261345"})

    def test_validate_only_dry_run(self):
        client, service, _operation, request = self._client()
        service.mutate_campaigns.return_value.results = []
        payload = _payload(
            update_campaign.call(
                client, {"customer_id": "123", "campaign_id": "55", "name": "X", "validate_only": True}
            )
        )
        self.assertTrue(request.validate_only)
        self.assertTrue(payload["validate_only"])
        self.assertFalse(payload["mutated"])


class CreateLabelTests(unittest.TestCase):
    def _client(self):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.mutate_labels.return_value.results = [SimpleNamespace(resource_name="customers/123/labels/999")]
        operation = mock.MagicMock(name="LabelOperation")
        request = mock.MagicMock(name="MutateLabelsRequest")

        def get_type(type_name):
            return {"LabelOperation": operation, "MutateLabelsRequest": request}.get(
                type_name, mock.MagicMock(name=type_name)
            )

        client.get_type.side_effect = get_type
        return client, service, operation, request

    def test_creates_label_and_returns_id(self):
        client, service, operation, request = self._client()
        result = create_label.call(
            client,
            {"customer_id": "1-2-3", "name": "High ROAS", "description": "d", "background_color": "#FF5733"},
        )
        self.assertEqual(operation.create.name, "High ROAS")
        self.assertEqual(operation.create.text_label.description, "d")
        self.assertEqual(operation.create.text_label.background_color, "#FF5733")
        service.mutate_labels.assert_called_once_with(request=request)
        payload = _payload(result)
        self.assertEqual(payload["customer_id"], "123")
        self.assertEqual(payload["label_resource_name"], "customers/123/labels/999")
        self.assertEqual(payload["label_id"], "999")
        self.assertTrue(payload["mutated"])

    def test_blank_name_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            create_label.call(client, {"customer_id": "123", "name": "   "})

    def test_validate_only_dry_run(self):
        client, service, _operation, _request = self._client()
        service.mutate_labels.return_value.results = []
        payload = _payload(create_label.call(client, {"customer_id": "123", "name": "X", "validate_only": True}))
        self.assertTrue(payload["validate_only"])
        self.assertFalse(payload["mutated"])
        self.assertIsNone(payload["label_id"])


class ApplyCampaignLabelTests(unittest.TestCase):
    def _client(self):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.campaign_path.return_value = "customers/123/campaigns/55"
        service.label_path.return_value = "customers/123/labels/999"
        service.mutate_campaign_labels.return_value.results = [
            SimpleNamespace(resource_name="customers/123/campaignLabels/55~999")
        ]
        operation = mock.MagicMock(name="CampaignLabelOperation")
        request = mock.MagicMock(name="MutateCampaignLabelsRequest")

        def get_type(type_name):
            return {"CampaignLabelOperation": operation, "MutateCampaignLabelsRequest": request}.get(
                type_name, mock.MagicMock(name=type_name)
            )

        client.get_type.side_effect = get_type
        return client, service, operation, request

    def test_applies_label_link(self):
        client, service, operation, request = self._client()
        result = apply_campaign_label.call(
            client,
            {"customer_id": "1-2-3", "campaign_id": "customers/123/campaigns/55", "label_id": "999"},
        )
        self.assertEqual(operation.create.campaign, "customers/123/campaigns/55")
        self.assertEqual(operation.create.label, "customers/123/labels/999")
        service.mutate_campaign_labels.assert_called_once_with(request=request)
        payload = _payload(result)
        self.assertEqual(payload["customer_id"], "123")
        self.assertEqual(payload["campaign_id"], "55")
        self.assertEqual(payload["label_id"], "999")
        self.assertTrue(payload["mutated"])


class RemoveCampaignLabelTests(unittest.TestCase):
    def _client(self):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.campaign_label_path.return_value = "customers/123/campaignLabels/55~999"
        service.mutate_campaign_labels.return_value.results = [
            SimpleNamespace(resource_name="customers/123/campaignLabels/55~999")
        ]
        operation = mock.MagicMock(name="CampaignLabelOperation")
        request = mock.MagicMock(name="MutateCampaignLabelsRequest")

        def get_type(type_name):
            return {"CampaignLabelOperation": operation, "MutateCampaignLabelsRequest": request}.get(
                type_name, mock.MagicMock(name=type_name)
            )

        client.get_type.side_effect = get_type
        return client, service, operation, request

    def test_removes_label_link(self):
        client, service, operation, request = self._client()
        result = remove_campaign_label.call(
            client, {"customer_id": "123", "campaign_id": "55", "label_id": "999"}
        )
        service.campaign_label_path.assert_called_once_with("123", "55", "999")
        self.assertEqual(operation.remove, "customers/123/campaignLabels/55~999")
        service.mutate_campaign_labels.assert_called_once_with(request=request)
        payload = _payload(result)
        self.assertTrue(payload["mutated"])

    def test_validate_only_dry_run(self):
        client, service, _operation, _request = self._client()
        service.mutate_campaign_labels.return_value.results = []
        payload = _payload(
            remove_campaign_label.call(
                client, {"customer_id": "123", "campaign_id": "55", "label_id": "999", "validate_only": True}
            )
        )
        self.assertTrue(payload["validate_only"])
        self.assertFalse(payload["mutated"])


# ── update_ad_group ───────────────────────────────────────────────────────────


class UpdateAdGroupTests(unittest.TestCase):
    def _client(self, result_name="customers/123/adGroups/44"):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.ad_group_path.return_value = result_name
        service.mutate_ad_groups.return_value.results = [SimpleNamespace(resource_name=result_name)]
        operation = mock.MagicMock(name="AdGroupOperation")
        request = mock.MagicMock(name="MutateAdGroupsRequest")
        client.get_type.side_effect = lambda t: {
            "AdGroupOperation": operation,
            "MutateAdGroupsRequest": request,
        }[t]
        return client, service, operation, request

    def test_status_sets_mask_and_calls_mutate(self):
        client, service, operation, request = self._client()
        result = update_ad_group.call(client, {"customer_id": "123", "ad_group_id": "44", "status": "PAUSED"})

        client.get_service.assert_called_with("AdGroupService")
        service.ad_group_path.assert_called_once_with("123", "44")
        self.assertEqual(operation.update.resource_name, "customers/123/adGroups/44")
        client.enums.AdGroupStatusEnum.__getitem__.assert_called_once_with("PAUSED")
        operation.update_mask.paths.append.assert_called_once_with("status")
        request.operations.append.assert_called_once_with(operation)
        service.mutate_ad_groups.assert_called_once_with(request=request)

        payload = _payload(result)
        self.assertEqual(payload["updated_fields"], ["status"])
        self.assertTrue(payload["mutated"])

    def test_rename_sets_name_mask(self):
        client, _service, operation, _request = self._client()
        update_ad_group.call(client, {"customer_id": "123", "ad_group_id": "44", "name": "New Name"})
        self.assertEqual(operation.update.name, "New Name")
        operation.update_mask.paths.append.assert_called_once_with("name")

    def test_bid_sets_cpc_bid_micros_mask(self):
        client, _service, operation, _request = self._client()
        result = update_ad_group.call(client, {"customer_id": "123", "ad_group_id": "44", "cpc_bid_micros": 500000})
        self.assertEqual(operation.update.cpc_bid_micros, 500000)
        operation.update_mask.paths.append.assert_called_once_with("cpc_bid_micros")
        self.assertEqual(_payload(result)["updated_fields"], ["cpc_bid_micros"])

    def test_multiple_fields_masked_together(self):
        client, _service, operation, _request = self._client()
        result = update_ad_group.call(
            client, {"customer_id": "123", "ad_group_id": "44", "status": "ENABLED", "cpc_bid_micros": 250000}
        )
        self.assertEqual(_payload(result)["updated_fields"], ["status", "cpc_bid_micros"])

    def test_no_editable_field_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_ad_group.call(client, {"customer_id": "123", "ad_group_id": "44"})

    def test_invalid_status_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_ad_group.call(client, {"customer_id": "123", "ad_group_id": "44", "status": "REMOVED"})

    def test_bid_over_ceiling_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_ad_group.call(
                client, {"customer_id": "123", "ad_group_id": "44", "cpc_bid_micros": 10_000_000_001}
            )

    def test_ad_group_id_accepts_resource_name(self):
        client, service, *_ = self._client()
        update_ad_group.call(
            client, {"customer_id": "123", "ad_group_id": "customers/123/adGroups/44", "status": "PAUSED"}
        )
        service.ad_group_path.assert_called_once_with("123", "44")

    def test_validate_only_sets_request_flag(self):
        client, service, _operation, request = self._client()
        service.mutate_ad_groups.return_value.results = []
        result = update_ad_group.call(
            client, {"customer_id": "123", "ad_group_id": "44", "status": "ENABLED", "validate_only": True}
        )
        self.assertTrue(request.validate_only)
        payload = _payload(result)
        self.assertTrue(payload["validate_only"])
        self.assertFalse(payload["mutated"])


# ── update_ad_group_ad ────────────────────────────────────────────────────────


class UpdateAdGroupAdTests(unittest.TestCase):
    def _client(self, result_name="customers/123/adGroupAds/44~88"):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.ad_group_ad_path.return_value = result_name
        service.mutate_ad_group_ads.return_value.results = [SimpleNamespace(resource_name=result_name)]
        operation = mock.MagicMock(name="AdGroupAdOperation")
        request = mock.MagicMock(name="MutateAdGroupAdsRequest")
        client.get_type.side_effect = lambda t: {
            "AdGroupAdOperation": operation,
            "MutateAdGroupAdsRequest": request,
        }[t]
        return client, service, operation, request

    def test_status_uses_compound_path_and_mask(self):
        client, service, operation, request = self._client()
        result = update_ad_group_ad.call(
            client, {"customer_id": "123", "ad_group_id": "44", "ad_id": "88", "status": "PAUSED"}
        )
        client.get_service.assert_called_with("AdGroupAdService")
        service.ad_group_ad_path.assert_called_once_with("123", "44", "88")
        client.enums.AdGroupAdStatusEnum.__getitem__.assert_called_once_with("PAUSED")
        operation.update_mask.paths.append.assert_called_once_with("status")
        service.mutate_ad_group_ads.assert_called_once_with(request=request)
        payload = _payload(result)
        self.assertEqual(payload["ad_id"], "88")
        self.assertEqual(payload["status"], "PAUSED")
        self.assertTrue(payload["mutated"])

    def test_status_normalized_uppercase(self):
        client, *_ = self._client()
        update_ad_group_ad.call(client, {"customer_id": "123", "ad_group_id": "44", "ad_id": "88", "status": "enabled"})
        client.enums.AdGroupAdStatusEnum.__getitem__.assert_called_once_with("ENABLED")

    def test_invalid_status_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_ad_group_ad.call(
                client, {"customer_id": "123", "ad_group_id": "44", "ad_id": "88", "status": "REMOVED"}
            )

    def test_validate_only_sets_request_flag(self):
        client, service, _operation, request = self._client()
        service.mutate_ad_group_ads.return_value.results = []
        result = update_ad_group_ad.call(
            client,
            {"customer_id": "123", "ad_group_id": "44", "ad_id": "88", "status": "ENABLED", "validate_only": True},
        )
        self.assertTrue(request.validate_only)
        self.assertFalse(_payload(result)["mutated"])


# ── update_ad_group_criterion ─────────────────────────────────────────────────


class UpdateAdGroupCriterionTests(unittest.TestCase):
    def _client(self, result_name="customers/123/adGroupCriteria/44~99"):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.ad_group_criterion_path.return_value = result_name
        service.mutate_ad_group_criteria.return_value.results = [SimpleNamespace(resource_name=result_name)]
        operation = mock.MagicMock(name="AdGroupCriterionOperation")
        request = mock.MagicMock(name="MutateAdGroupCriteriaRequest")
        client.get_type.side_effect = lambda t: {
            "AdGroupCriterionOperation": operation,
            "MutateAdGroupCriteriaRequest": request,
        }[t]
        return client, service, operation, request

    def test_status_uses_compound_path_and_mask(self):
        client, service, operation, request = self._client()
        result = update_ad_group_criterion.call(
            client, {"customer_id": "123", "ad_group_id": "44", "criterion_id": "99", "status": "PAUSED"}
        )
        client.get_service.assert_called_with("AdGroupCriterionService")
        service.ad_group_criterion_path.assert_called_once_with("123", "44", "99")
        client.enums.AdGroupCriterionStatusEnum.__getitem__.assert_called_once_with("PAUSED")
        operation.update_mask.paths.append.assert_called_once_with("status")
        service.mutate_ad_group_criteria.assert_called_once_with(request=request)
        payload = _payload(result)
        self.assertEqual(payload["criterion_id"], "99")
        self.assertEqual(payload["updated_fields"], ["status"])

    def test_bid_sets_cpc_bid_micros_mask(self):
        client, _service, operation, _request = self._client()
        result = update_ad_group_criterion.call(
            client, {"customer_id": "123", "ad_group_id": "44", "criterion_id": "99", "cpc_bid_micros": 750000}
        )
        self.assertEqual(operation.update.cpc_bid_micros, 750000)
        operation.update_mask.paths.append.assert_called_once_with("cpc_bid_micros")
        self.assertEqual(_payload(result)["updated_fields"], ["cpc_bid_micros"])

    def test_no_editable_field_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_ad_group_criterion.call(client, {"customer_id": "123", "ad_group_id": "44", "criterion_id": "99"})

    def test_bid_over_ceiling_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            update_ad_group_criterion.call(
                client,
                {"customer_id": "123", "ad_group_id": "44", "criterion_id": "99", "cpc_bid_micros": 10_000_000_001},
            )


# ── add_negative_keyword ──────────────────────────────────────────────────────


class AddNegativeKeywordTests(unittest.TestCase):
    def _client(self):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.ad_group_path.return_value = "customers/123/adGroups/44"
        service.campaign_path.return_value = "customers/123/campaigns/55"
        service.mutate_ad_group_criteria.return_value.results = [
            SimpleNamespace(resource_name="customers/123/adGroupCriteria/44~1")
        ]
        service.mutate_campaign_criteria.return_value.results = [
            SimpleNamespace(resource_name="customers/123/campaignCriteria/55~2")
        ]
        ag_op = mock.MagicMock(name="AdGroupCriterionOperation")
        ag_req = mock.MagicMock(name="MutateAdGroupCriteriaRequest")
        c_op = mock.MagicMock(name="CampaignCriterionOperation")
        c_req = mock.MagicMock(name="MutateCampaignCriteriaRequest")
        client.get_type.side_effect = lambda t: {
            "AdGroupCriterionOperation": ag_op,
            "MutateAdGroupCriteriaRequest": ag_req,
            "CampaignCriterionOperation": c_op,
            "MutateCampaignCriteriaRequest": c_req,
        }[t]
        return client, service, ag_op, ag_req, c_op, c_req

    def test_ad_group_negative_defaults_exact(self):
        client, service, ag_op, ag_req, *_ = self._client()
        result = add_negative_keyword.call(client, {"customer_id": "123", "ad_group_id": "44", "text": "cheap"})

        client.get_service.assert_called_with("AdGroupCriterionService")
        service.ad_group_path.assert_called_once_with("123", "44")
        self.assertEqual(ag_op.create.ad_group, "customers/123/adGroups/44")
        self.assertTrue(ag_op.create.negative)
        self.assertEqual(ag_op.create.keyword.text, "cheap")
        client.enums.KeywordMatchTypeEnum.__getitem__.assert_called_once_with("EXACT")  # default
        service.mutate_ad_group_criteria.assert_called_once_with(request=ag_req)

        payload = _payload(result)
        self.assertEqual(payload["level"], "ad_group")
        self.assertEqual(payload["ad_group_id"], "44")
        self.assertIsNone(payload["campaign_id"])
        self.assertEqual(payload["match_type"], "EXACT")
        self.assertTrue(payload["negative"])
        self.assertTrue(payload["mutated"])

    def test_campaign_negative_normalizes_match_type(self):
        client, service, _agop, _agreq, c_op, c_req = self._client()
        result = add_negative_keyword.call(
            client, {"customer_id": "123", "campaign_id": "55", "text": "free stuff", "match_type": "phrase"}
        )
        client.get_service.assert_called_with("CampaignCriterionService")
        service.campaign_path.assert_called_once_with("123", "55")
        self.assertTrue(c_op.create.negative)
        self.assertEqual(c_op.create.keyword.text, "free stuff")
        client.enums.KeywordMatchTypeEnum.__getitem__.assert_called_once_with("PHRASE")  # normalized upper
        service.mutate_campaign_criteria.assert_called_once_with(request=c_req)

        payload = _payload(result)
        self.assertEqual(payload["level"], "campaign")
        self.assertEqual(payload["campaign_id"], "55")
        self.assertIsNone(payload["ad_group_id"])

    def test_requires_exactly_one_target(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):  # neither
            add_negative_keyword.call(client, {"customer_id": "123", "text": "x"})
        with self.assertRaises(ValueError):  # both
            add_negative_keyword.call(
                client, {"customer_id": "123", "ad_group_id": "44", "campaign_id": "55", "text": "x"}
            )

    def test_invalid_match_type_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            add_negative_keyword.call(
                client, {"customer_id": "123", "ad_group_id": "44", "text": "x", "match_type": "NEAR"}
            )

    def test_empty_text_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            add_negative_keyword.call(client, {"customer_id": "123", "ad_group_id": "44", "text": "   "})

    def test_overlong_text_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            add_negative_keyword.call(client, {"customer_id": "123", "campaign_id": "55", "text": "x" * 81})

    def test_validate_only_sets_request_flag(self):
        client, service, _agop, ag_req, *_ = self._client()
        service.mutate_ad_group_criteria.return_value.results = []
        result = add_negative_keyword.call(
            client, {"customer_id": "123", "ad_group_id": "44", "text": "cheap", "validate_only": True}
        )
        self.assertTrue(ag_req.validate_only)
        payload = _payload(result)
        self.assertTrue(payload["validate_only"])
        self.assertFalse(payload["mutated"])


# ── remove_negative_keyword ───────────────────────────────────────────────────


class RemoveNegativeKeywordTests(unittest.TestCase):
    def _client(self):
        client = mock.MagicMock()
        service = client.get_service.return_value
        service.ad_group_criterion_path.return_value = "customers/123/adGroupCriteria/44~99"
        service.campaign_criterion_path.return_value = "customers/123/campaignCriteria/55~99"
        service.mutate_ad_group_criteria.return_value.results = [
            SimpleNamespace(resource_name="customers/123/adGroupCriteria/44~99")
        ]
        service.mutate_campaign_criteria.return_value.results = [
            SimpleNamespace(resource_name="customers/123/campaignCriteria/55~99")
        ]
        ag_op = mock.MagicMock(name="AdGroupCriterionOperation")
        ag_req = mock.MagicMock(name="MutateAdGroupCriteriaRequest")
        c_op = mock.MagicMock(name="CampaignCriterionOperation")
        c_req = mock.MagicMock(name="MutateCampaignCriteriaRequest")
        client.get_type.side_effect = lambda t: {
            "AdGroupCriterionOperation": ag_op,
            "MutateAdGroupCriteriaRequest": ag_req,
            "CampaignCriterionOperation": c_op,
            "MutateCampaignCriteriaRequest": c_req,
        }[t]
        return client, service, ag_op, ag_req, c_op, c_req

    def test_ad_group_remove_uses_remove_op(self):
        client, service, ag_op, ag_req, *_ = self._client()
        result = remove_negative_keyword.call(client, {"customer_id": "123", "ad_group_id": "44", "criterion_id": "99"})

        client.get_service.assert_called_with("AdGroupCriterionService")
        service.ad_group_criterion_path.assert_called_once_with("123", "44", "99")
        self.assertEqual(ag_op.remove, "customers/123/adGroupCriteria/44~99")
        service.mutate_ad_group_criteria.assert_called_once_with(request=ag_req)

        payload = _payload(result)
        self.assertEqual(payload["level"], "ad_group")
        self.assertEqual(payload["criterion_id"], "99")
        self.assertTrue(payload["mutated"])

    def test_campaign_remove_uses_remove_op(self):
        client, service, _agop, _agreq, c_op, c_req = self._client()
        result = remove_negative_keyword.call(client, {"customer_id": "123", "campaign_id": "55", "criterion_id": "99"})

        client.get_service.assert_called_with("CampaignCriterionService")
        service.campaign_criterion_path.assert_called_once_with("123", "55", "99")
        self.assertEqual(c_op.remove, "customers/123/campaignCriteria/55~99")
        service.mutate_campaign_criteria.assert_called_once_with(request=c_req)
        self.assertEqual(_payload(result)["level"], "campaign")

    def test_requires_exactly_one_target(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            remove_negative_keyword.call(client, {"customer_id": "123", "criterion_id": "99"})
        with self.assertRaises(ValueError):
            remove_negative_keyword.call(
                client, {"customer_id": "123", "ad_group_id": "44", "campaign_id": "55", "criterion_id": "99"}
            )

    def test_missing_criterion_id_raises(self):
        client, *_ = self._client()
        with self.assertRaises(ValueError):
            remove_negative_keyword.call(client, {"customer_id": "123", "campaign_id": "55"})

    def test_validate_only_sets_request_flag(self):
        client, service, _agop, ag_req, *_ = self._client()
        service.mutate_ad_group_criteria.return_value.results = []
        result = remove_negative_keyword.call(
            client, {"customer_id": "123", "ad_group_id": "44", "criterion_id": "99", "validate_only": True}
        )
        self.assertTrue(ag_req.validate_only)
        self.assertFalse(_payload(result)["mutated"])


if __name__ == "__main__":
    unittest.main()

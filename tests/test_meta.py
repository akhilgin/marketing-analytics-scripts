import unittest
from datetime import date

import _paths  # noqa: F401
import daily_report as dr
import meta_ads_client as mc


class ClientHelpers(unittest.TestCase):
    def test_account_id(self):
        self.assertEqual(mc.normalize_account_id("1234567890"), "act_1234567890")
        self.assertEqual(mc.normalize_account_id("act_1234567890"), "act_1234567890")
        for bad in ("", None, "act_", "abc"):
            with self.assertRaises(ValueError):
                mc.normalize_account_id(bad)

    def test_conversions(self):
        actions = [{"action_type": "lead", "value": "3"},
                   {"action_type": "link_click", "value": "50"},
                   {"action_type": "offsite_conversion.fb_pixel_lead", "value": "2"}]
        self.assertEqual(mc.extract_conversions(actions), 5)
        self.assertEqual(mc.extract_conversions(actions, ("lead",)), 3)
        self.assertEqual(mc.extract_conversions(None), 0)

    def test_time_range(self):
        self.assertEqual(mc.time_range_param(date(2026, 1, 1), date(2026, 1, 7)),
                         '{"since":"2026-01-01","until":"2026-01-07"}')

    def test_missing_token(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                mc.MetaAdsClient("act_1234567890")


class ReportMath(unittest.TestCase):
    ROW = {"spend": "50", "impressions": "10000", "clicks": "100", "reach": "8000",
           "actions": [{"action_type": "lead", "value": "5"}],
           "date_start": "2026-01-02", "campaign_id": "1", "campaign_name": "Campaign A"}

    def test_parse(self):
        p = dr.parse_insights_row(self.ROW)
        self.assertAlmostEqual(p["ctr"], 1.0)
        self.assertAlmostEqual(p["cpc"], 0.5)
        self.assertAlmostEqual(p["cpm"], 5.0)
        self.assertAlmostEqual(p["cpl"], 10.0)

    def test_aggregate_recomputes_ratios(self):
        a = dr.parse_insights_row(self.ROW)
        b = dr.parse_insights_row({**self.ROW, "spend": "150", "clicks": "100", "actions": []})
        t = dr.aggregate_metrics([a, b])
        self.assertEqual(t["spend"], 200)
        self.assertAlmostEqual(t["cpc"], 1.0)  # not the average of 0.5 and 1.5
        self.assertAlmostEqual(t["cpl"], 40.0)

    def test_empty(self):
        t = dr.aggregate_metrics([])
        self.assertEqual((t["ctr"], t["cpc"], t["cpl"]), (0, 0, 0))

    def test_delta(self):
        self.assertEqual(dr.delta_str(110, 100), "+10%")
        self.assertEqual(dr.delta_str(80, 100), "-20%")
        self.assertEqual(dr.delta_str(0, 0), "n/a")
        self.assertEqual(dr.delta_str(5, 0), "new")

    def test_flags(self):
        self.assertEqual(dr.benchmark_flag(1.2, 1.0), "OK")
        self.assertEqual(dr.benchmark_flag(0.9, 1.0), "WARN")
        self.assertEqual(dr.benchmark_flag(0.5, 1.0), "BAD")
        self.assertEqual(dr.benchmark_flag(3.5, 3, higher_is_better=False), "WARN")
        self.assertEqual(dr.benchmark_flag(0, 3), "-")

    def test_pacing(self):
        self.assertEqual(dr.pacing_status(500, 1000, 15, 30), "on track")
        self.assertEqual(dr.pacing_status(100, 1000, 15, 30), "underpacing")
        self.assertEqual(dr.pacing_status(900, 1000, 15, 30), "overpacing")
        self.assertEqual(dr.pacing_status(100, 0, 15, 30), "no budget set")

    def test_alerts(self):
        yday = dr.aggregate_metrics([dr.parse_insights_row(self.ROW)])
        avg7 = {**yday, "ctr": 2.0}
        camp = [dr.parse_insights_row({**self.ROW, "actions": [], "spend": "300"})]
        alerts = dr.build_alerts(yday, avg7, camp, {}, dr.DEFAULT_BENCHMARKS, 200)
        kinds = [(a[0], a[2]) for a in alerts]
        self.assertIn(("P1", "CTR drop"), kinds)
        self.assertIn(("P0", "No conversions"), kinds)
        self.assertEqual(alerts[0][0], "P0")


if __name__ == "__main__":
    unittest.main()

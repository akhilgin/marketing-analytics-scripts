import os
import unittest
from unittest import mock

import _paths  # noqa: F401
import ga4_common as c
import ai_assistant_ads_report as ai
import paid_traffic_report as paid


class PaidClassification(unittest.TestCase):
    def test_channel_groups(self):
        for g in ("Paid Search", "paid social", "Display", "Paid Other"):
            self.assertTrue(c.is_paid_session(g, "(none)"), g)

    def test_medium_rules(self):
        self.assertTrue(c.is_paid_session("Unassigned", "cpc"))
        self.assertTrue(c.is_paid_session("Unassigned", "PPC"))
        self.assertTrue(c.is_paid_session("Unassigned", "paid-newsletter"))
        self.assertTrue(c.is_paid_session("Referral", "sponsored_post"))

    def test_not_paid(self):
        self.assertFalse(c.is_paid_session("Organic Search", "organic"))
        self.assertFalse(c.is_paid_session("Direct", "(none)"))
        self.assertFalse(c.is_paid_session(None, None))
        # exact match only for cpc/ppc
        self.assertFalse(c.is_paid_session("Referral", "cpc-test"))


class Formatting(unittest.TestCase):
    def test_avg_engagement_uses_total_over_sessions(self):
        self.assertEqual(c.fmt_avg_engagement(600, 10), "1m 00s")
        self.assertEqual(c.fmt_avg_engagement(450, 10), "45s")
        self.assertEqual(c.fmt_avg_engagement(100, 0), "0s")

    def test_numbers(self):
        self.assertEqual(c.fmt_int("1234.6"), "1,235")
        self.assertEqual(c.fmt_pct("0.4567", 2), "45.67%")
        self.assertEqual(c.safe_div(1, 0), 0.0)

    def test_table(self):
        self.assertEqual(c.fmt_table(["a"], []), "(no data)")
        t = c.fmt_table(["name", "n"], [["x", 1], ["longer", 22]])
        self.assertEqual(t.splitlines()[0], "name   | n ")
        self.assertEqual(len(t.splitlines()), 4)

    def test_table_truncates(self):
        t = c.fmt_table(["h"], [["x" * 100]], max_col_width=10)
        self.assertEqual(len(t.splitlines()[2]), 10)


class PropertyHandling(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(c.normalize_property_id("properties/123456789"), "123456789")
        self.assertEqual(c.normalize_property_id(" 42 "), "42")
        self.assertIsNone(c.normalize_property_id("G-XXXXXXXXXX"))
        self.assertIsNone(c.normalize_property_id(None))

    def test_resolve_from_env(self):
        with mock.patch.dict(os.environ, {"GA4_PROPERTY_ID": "123456789"}):
            self.assertEqual(c.resolve_property(None), "123456789")
            self.assertEqual(c.resolve_property("987654321"), "987654321")

    def test_resolve_missing_exits(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                c.resolve_property(None)


class PaidReportRows(unittest.TestCase):
    def test_format_row(self):
        row = paid.format_row(["google / cpc"], ["80", "100", "60", "0.6", "3000"])
        self.assertEqual(row, ["google / cpc", "80", "100", "60", "60.00%", "30s"])


class AiAdsSegment(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(ai.matches_ai_ads("ChatGPT", "paid", ["chatgpt"]))
        self.assertTrue(ai.matches_ai_ads("chatgpt-ads", "Paid_AI", ["chatgpt"]))

    def test_excludes_organic_referrals(self):
        self.assertFalse(ai.matches_ai_ads("chatgpt.com", "referral", ["chatgpt"]))
        self.assertFalse(ai.matches_ai_ads("chatgpt", "ai-assistant", ["chatgpt"]))
        self.assertFalse(ai.matches_ai_ads("(direct)", "paid", ["chatgpt"]))

    def test_multiple_terms(self):
        self.assertTrue(ai.matches_ai_ads("perplexity", "paid", ["chatgpt", "perplexity"]))

    def test_quality_rows(self):
        d = {"sessions": 10, "totalUsers": 5, "engagedSessions": 5, "engagementRate": 0.5,
             "userEngagementDuration": 300, "screenPageViews": 25, "keyEvents": 2}
        rows = dict(ai.quality_rows(d, "keyEvents"))
        self.assertEqual(rows["Engagement Rate"], "50.0%")
        self.assertEqual(rows["Avg Engagement Time / Session"], "30s")
        self.assertEqual(rows["Sessions / User"], "2.00")
        self.assertEqual(rows["keyEvents / Session"], "0.200")


if __name__ == "__main__":
    unittest.main()

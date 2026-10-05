import unittest

import _paths  # noqa: F401
import gtm


def checks(findings):
    return {(f["check"], f["item"]) for f in findings}


class Audit(unittest.TestCase):
    def setUp(self):
        self.tags = [
            {"tagId": "1", "name": "GA4 config", "type": "googtag", "firingTriggerId": ["10"],
             "parameter": [{"key": "tagId", "value": "{{Measurement ID}}"}]},
            {"tagId": "2", "name": "Old", "type": "ua", "paused": True},
            {"tagId": "3", "name": "Orphan", "type": "html"},
            {"tagId": "4", "name": "Typed ID", "type": "gaawe", "firingTriggerId": ["10"],
             "blockingTriggerId": ["12"],
             "parameter": [{"key": "measurementId", "value": "G-XXXXXXXXXX"}]},
            {"tagId": "5", "name": "Orphan", "type": "html", "firingTriggerId": ["10"]},
        ]
        self.triggers = [{"triggerId": "10", "name": "All pages"},
                         {"triggerId": "11", "name": "Unused"},
                         {"triggerId": "12", "name": "Blocker"}]
        self.variables = [{"variableId": "20", "name": "Measurement ID", "type": "c"},
                          {"variableId": "21", "name": "Stale", "type": "c"}]
        self.f = gtm.audit_container(self.tags, self.triggers, self.variables)
        self.by_check = {}
        for x in self.f:
            self.by_check.setdefault(x["check"], []).append(x["item"])

    def test_paused_and_legacy(self):
        self.assertEqual(len(self.by_check["paused_tag"]), 1)
        self.assertEqual(len(self.by_check["legacy_universal_analytics"]), 1)

    def test_no_trigger_ignores_paused(self):
        self.assertEqual(self.by_check["tag_without_trigger"], ["tag 3 'Orphan'"])

    def test_duplicates(self):
        self.assertEqual(len(self.by_check["duplicate_tag_name"]), 2)

    def test_unused_trigger_counts_blocking(self):
        self.assertEqual(self.by_check["unused_trigger"], ["trigger 11 'Unused'"])

    def test_variables(self):
        self.assertEqual(self.by_check["unused_variable"], ["variable 21 'Stale'"])

    def test_hardcoded_id(self):
        self.assertEqual(self.by_check["hardcoded_measurement_id"], ["tag 4 'Typed ID'"])

    def test_format(self):
        text = gtm.format_findings(self.f)
        self.assertIn("warn", text)
        self.assertEqual(gtm.format_findings([]), "No findings.")


class DryRun(unittest.TestCase):
    def test_not_applied_by_default(self):
        class A:
            apply = False
        called = []
        self.assertIsNone(gtm.dry_run_or(A, "do a thing", lambda: called.append(1)))
        self.assertEqual(called, [])

    def test_applied_with_flag(self):
        class A:
            apply = True
        self.assertEqual(gtm.dry_run_or(A, "do a thing", lambda: 7), 7)

    def test_write_commands_require_apply_flag_default_false(self):
        p = gtm.build_parser()
        for argv in (["tags", "pause", "1"], ["tags", "delete", "1"],
                     ["create-version", "--name", "x"], ["publish", "3"]):
            self.assertFalse(p.parse_args(argv).apply, argv)
        self.assertTrue(p.parse_args(["publish", "3", "--apply"]).apply)


if __name__ == "__main__":
    unittest.main()

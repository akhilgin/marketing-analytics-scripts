import unittest

import _paths  # noqa: F401
import broken_links_404_audit as audit
import email_launch_monitor as mon


class ErrorTitles(unittest.TestCase):
    def test_detects(self):
        self.assertTrue(audit.is_error_title("Page Not Found | Example"))
        self.assertTrue(audit.is_error_title("404"))
        self.assertFalse(audit.is_error_title("Pricing"))
        self.assertFalse(audit.is_error_title(None))

    def test_custom_patterns(self):
        self.assertFalse(audit.is_error_title("Common errors", ["page not found"]))
        self.assertTrue(audit.is_error_title("Oops, gone", ["oops"]))


class PathNormalization(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(audit.normalize_path("/blog/post/"), "/blog/post")
        self.assertEqual(audit.normalize_path("/blog//post?utm=1#x"), "/blog/post")
        self.assertEqual(audit.normalize_path("/"), "/")
        self.assertEqual(audit.normalize_path(""), "/")
        self.assertEqual(audit.normalize_path("/Case"), "/Case")

    def test_merge(self):
        rows = [["/old/", "Not found", "5", "3", "4"],
                ["/old", "Not found", "10", "6", "8"],
                ["/other", "Not found", "1", "1", "1"]]
        merged = audit.merge_by_normalized_path(rows)
        self.assertEqual(merged[0], ["/old", "Not found", 15, 9, 12])
        self.assertEqual(len(merged), 2)


class MonitorHelpers(unittest.TestCase):
    def test_minute_windows(self):
        w = mon.minute_windows({0: 3, 4: 2, 5: 1, 29: 7, 30: 99})
        self.assertEqual(w[0], (0, 4, 5))
        self.assertEqual(w[1], (5, 9, 1))
        self.assertEqual(w[-1], (25, 29, 7))
        self.assertEqual(len(w), 6)

    def test_filter_rows(self):
        rows = [["/Webinar/x", "3"], ["/pricing", "1"]]
        self.assertEqual(mon.filter_rows(rows, "webinar"), [rows[0]])
        self.assertEqual(mon.filter_rows(rows, None), rows)


if __name__ == "__main__":
    unittest.main()

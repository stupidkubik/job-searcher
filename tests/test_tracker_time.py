import unittest
from datetime import datetime, timezone

from scripts import tracker_time


class TrackerTimeTests(unittest.TestCase):
    def test_business_date_uses_belgrade_at_utc_midnight_boundary(self):
        instant = datetime(2026, 8, 13, 22, 17, 45, tzinfo=timezone.utc)

        self.assertEqual(tracker_time.business_date(instant).isoformat(), "2026-08-14")
        self.assertEqual(tracker_time.utc_timestamp(instant), "2026-08-13T22:17:45Z")

    def test_clock_rejects_naive_instants(self):
        with self.assertRaisesRegex(ValueError, "timezone information"):
            tracker_time.business_date(datetime(2026, 8, 14, 0, 0))


if __name__ == "__main__":
    unittest.main()

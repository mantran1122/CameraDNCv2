import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from temporal_parser import parse_query_temporal
from vss_search_engine import search_vss_archive


from ai_search_planner import plan_search_intent


class TemporalAndSearchTest(unittest.TestCase):
    def test_parse_hour_range(self):
        res = parse_query_temporal("sự kiện bất thường từ 7h đến 8h hôm nay")
        self.assertTrue(res["is_time_filtered"])
        self.assertTrue(res["is_date_filtered"])
        self.assertTrue(res["only_anomalies"])
        self.assertIn("07:00:00", res["start_time"])
        self.assertIn("08:00:59", res["end_time"])

    def test_search_vss_empty_when_no_match(self):
        # 07:00 to 08:00 on Cam 11 has no events
        res = search_vss_archive("sự kiện từ 7h đến 8h hôm nay", {"channel": 11})
        self.assertEqual(len(res["data"]), 0)
        self.assertEqual(res["total_matches"], 0)

    def test_search_vss_empty_explicit_event_ids(self):
        res = search_vss_archive("bất thường", {"channel": 11, "event_ids": []})
        self.assertEqual(len(res["data"]), 0)
        self.assertEqual(res["total_matches"], 0)

    def test_ai_planner_all_cameras_intent(self):
        # Query asking for all anomalies must resolve to channel=None even if selected_channel is 11
        res = plan_search_intent("hiển thị ra tất cả sự kiện bất thường hôm nay", selected_channel=11)
        self.assertTrue(res["is_all_channels"])
        self.assertIsNone(res["channel"])
        self.assertTrue(res["only_anomalies"])

    def test_ai_planner_explicit_channel(self):
        # Query naming cam 18 must resolve to channel=18
        res = plan_search_intent("kênh 18 có gì bất thường không", selected_channel=11)
        self.assertFalse(res["is_all_channels"])
        self.assertEqual(res["channel"], 18)
        self.assertTrue(res["only_anomalies"])

    def test_search_vss_multi_camera_event_ids(self):
        # When event_ids from multiple channels are passed, they should not be dropped by channel filter
        # Event 23916 is Cam 11, Event 24231 is Cam 18
        res = search_vss_archive("tất cả sự kiện bất thường", {"event_ids": [23916, 24231], "channel": 11})
        returned_ids = [item["id"] for item in res["data"]]
        self.assertIn(23916, returned_ids)
        self.assertIn(24231, returned_ids)


if __name__ == "__main__":
    unittest.main()



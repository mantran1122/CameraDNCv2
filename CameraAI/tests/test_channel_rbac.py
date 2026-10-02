import unittest
import json
from pathlib import Path
from fastapi.testclient import TestClient

import main
import database
import config


class ChannelRBACTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def setUp(self):
        main.login_rate_limiter.reset()
        self.client = TestClient(main.app)
        self.admin_user, self.admin_pass = main.get_admin_credentials()

        # Seed sample test events in database
        self.seed_test_events()

        # Reset users.json to clean state with test sub-users
        test_users = [
            {
                "username": self.admin_user,
                "password": self.admin_pass,
                "role": "admin",
                "full_name": "Quản trị viên Hệ thống",
                "can_config_nvr": True,
                "allowed_channels": ["*"],
                "created_at": "2026-09-21T00:00:00"
            },
            {
                "username": "user_cam11",
                "password": "Password123@",
                "role": "viewer",
                "full_name": "Nhân viên Kênh 11",
                "can_config_nvr": False,
                "allowed_channels": [11],
                "created_at": "2026-09-22T10:00:00"
            },
            {
                "username": "user_cam18_19",
                "password": "Password123@",
                "role": "operator",
                "full_name": "Nhân viên Sảnh 18 19",
                "can_config_nvr": False,
                "allowed_channels": [18, 19],
                "created_at": "2026-09-22T10:00:00"
            }
        ]
        main.save_system_users(test_users)

    def tearDown(self):
        main.login_rate_limiter.reset()
        self.client.close()

    def seed_test_events(self):
        conn = database.get_db_connection()
        cur = conn.cursor()
        # Insert events for channel 11 and channel 18
        cur.execute(
            """
            INSERT OR REPLACE INTO events (id, timestamp, channel, event_type, event_code, severity, description, clip_filename)
            VALUES 
            (99011, '2026-09-30 10:00:00', 11, 'video_anomaly', 'Intrusion', 'high', 'Người lạ vào phòng HSSV', 'cameras/cam-011/2026/09/30/evt_cam-011_20260930T100000_99011.mp4'),
            (99018, '2026-09-30 10:05:00', 18, 'video_anomaly', 'CrossLine', 'medium', 'Vượt rào sảnh 1', 'cameras/cam-018/2026/09/30/evt_cam-018_20260930T100500_99018.mp4')
            """
        )
        conn.commit()
        conn.close()

    def login_as(self, username, password):
        resp = self.client.post(
            "/api/admin/verify-login",
            json={"username": username, "password": password}
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_user_management_crud_with_allowed_channels(self):
        # 1. Login as Admin
        self.login_as(self.admin_user, self.admin_pass)

        # 2. Create new sub-user with allowed_channels = [1, 2, 5]
        create_resp = self.client.post(
            "/api/admin/users",
            json={
                "username": "test_rbac_user",
                "password": "Password456@",
                "role": "viewer",
                "full_name": "Test RBAC User",
                "allowed_channels": [1, 2, 5]
            }
        )
        self.assertEqual(create_resp.status_code, 200)

        # 3. List users and verify allowed_channels
        list_resp = self.client.get("/api/admin/users")
        self.assertEqual(list_resp.status_code, 200)
        users = list_resp.json()
        target = next((u for u in users if u["username"] == "test_rbac_user"), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["allowed_channels"], [1, 2, 5])

        # 4. Update user's allowed_channels via PUT
        update_resp = self.client.put(
            "/api/admin/users/test_rbac_user",
            json={
                "allowed_channels": [5, 7, 11],
                "full_name": "Updated RBAC User"
            }
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["user"]["allowed_channels"], [5, 7, 11])
        self.assertEqual(update_resp.json()["user"]["full_name"], "Updated RBAC User")

    def test_api_events_filtered_by_user_permissions(self):
        # Login as user_cam11 (allowed: [11])
        self.login_as("user_cam11", "Password123@")

        # Query all events
        resp = self.client.get("/api/events")
        self.assertEqual(resp.status_code, 200)
        events = resp.json()["events"]
        channels = {e["channel"] for e in events}
        # MUST only contain channel 11, cannot contain channel 18
        self.assertTrue(channels.issubset({11}))
        self.assertNotIn(18, channels)

        # Querying specifically for disallowed channel 18 returns empty
        resp_disallowed = self.client.get("/api/events?channel=18")
        self.assertEqual(resp_disallowed.status_code, 200)
        self.assertEqual(resp_disallowed.json()["events"], [])

    def test_api_event_detail_blocks_disallowed_channel(self):
        # Login as user_cam11
        self.login_as("user_cam11", "Password123@")

        # Event 99011 (ch 11) is allowed
        resp_ok = self.client.get("/api/events/99011")
        self.assertEqual(resp_ok.status_code, 200)

        # Event 99018 (ch 18) must return 403 Forbidden
        resp_blocked = self.client.get("/api/events/99018")
        self.assertEqual(resp_blocked.status_code, 403)

    def test_clip_serving_blocks_disallowed_channel(self):
        # Login as user_cam11
        self.login_as("user_cam11", "Password123@")

        # Requesting clip from channel 18 must return 403
        resp_blocked = self.client.get("/clips/cameras/cam-018/2026/09/30/evt_cam-018_20260930T100500_99018.mp4")
        self.assertEqual(resp_blocked.status_code, 403)
        self.assertIn("không có quyền xem video clip", resp_blocked.json()["detail"])

        # Also via /api/clips/
        resp_api_blocked = self.client.get("/api/clips/cameras/cam-018/2026/09/30/evt_cam-018_20260930T100500_99018.mp4")
        self.assertEqual(resp_api_blocked.status_code, 403)

    def test_live_stream_blocks_disallowed_channel(self):
        # Login as user_cam11
        self.login_as("user_cam11", "Password123@")

        # Channel 18 must return 403
        resp_blocked = self.client.get("/api/stream/live/18")
        self.assertEqual(resp_blocked.status_code, 403)

    def test_agent_query_denies_disallowed_channel(self):
        # Login as user_cam11
        self.login_as("user_cam11", "Password123@")

        resp = self.client.post(
            "/api/agent/query",
            json={"query": "Tình hình camera sảnh kênh 18 thế nào?", "channel": 18}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("không có quyền truy cập", data["reply"])
        self.assertEqual(data["matched_events"], [])

    def test_allowed_cameras_api(self):
        # Login as user_cam18_19
        self.login_as("user_cam18_19", "Password123@")

        resp = self.client.get("/api/user/allowed-cameras")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["username"], "user_cam18_19")
        self.assertFalse(data["is_admin"])
        channels = [c["channel"] for c in data["cameras"]]
        self.assertEqual(channels, [18, 19])

        # Login as Admin -> should have all active channels
        self.login_as(self.admin_user, self.admin_pass)
        resp_admin = self.client.get("/api/user/allowed-cameras")
        self.assertEqual(resp_admin.status_code, 200)
        data_admin = resp_admin.json()
        self.assertTrue(data_admin["is_admin"])
        admin_channels = [c["channel"] for c in data_admin["cameras"]]
        self.assertEqual(admin_channels, sorted(config.ACTIVE_CHANNELS))


    def test_vss_search_filtered_by_permissions(self):
        # Login as user_cam11
        self.login_as("user_cam11", "Password123@")

        # Disallowed channel in search query
        resp_blocked = self.client.post(
            "/api/vss/search",
            json={"query": "tìm người", "channel": 18}
        )
        self.assertEqual(resp_blocked.status_code, 200)
        self.assertEqual(resp_blocked.json()["data"], [])
        self.assertIn("không có quyền", resp_blocked.json()["message"])

    def test_websocket_channel_filtering(self):
        import asyncio
        self.login_as("user_cam11", "Password123@")
        with self.client.websocket_connect("/ws") as ws:
            # Broadcast event for channel 18 (should not be delivered to user_cam11)
            asyncio.run(main.manager.broadcast({"id": 101, "channel": 18, "description": "cam 18 event"}))
            # Broadcast event for channel 11 (should be delivered)
            asyncio.run(main.manager.broadcast({"id": 102, "channel": 11, "description": "cam 11 event"}))
            msg = ws.receive_json()
            self.assertEqual(msg["channel"], 11)
            self.assertEqual(msg["id"], 102)


if __name__ == "__main__":
    unittest.main()

import unittest
import json
from fastapi.testclient import TestClient

import main
import database
import config


class AdminPortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def setUp(self):
        main.login_rate_limiter.reset()
        self.client = TestClient(main.app)
        self.admin_user, self.admin_pass = main.get_admin_credentials()

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
                "username": "viewer_user",
                "password": "Password123@",
                "role": "viewer",
                "full_name": "Nhân viên Giám sát",
                "can_config_nvr": False,
                "allowed_channels": [11, 18],
                "created_at": "2026-09-22T10:00:00"
            }
        ]
        main.save_system_users(test_users)

    def tearDown(self):
        main.login_rate_limiter.reset()
        self.client.close()

    def login(self, username, password):
        res = self.client.post("/api/admin/verify-login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200)
        return res

    def test_admin_page_unauthenticated_redirect(self):
        """Unauthenticated user accessing /admin should be redirected to /login."""
        res = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers.get("location"), "/login")

    def test_admin_page_forbidden_for_viewer(self):
        """Logged-in viewer accessing /admin should get 403 Forbidden."""
        self.login("viewer_user", "Password123@")
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Truy cập bị từ chối", res.json()["detail"])

    def test_admin_page_success_for_admin(self):
        """Logged-in admin accessing /admin gets 200 OK and Quasar template."""
        self.login(self.admin_user, self.admin_pass)
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Trung tâm Quản trị Quasar", res.text)
        self.assertIn("q-app", res.text)
        self.assertTrue("/static/js/admin_quasar.js" in res.text or "assets/index-" in res.text)

    def test_get_all_system_cameras(self):
        """Admin can retrieve full catalog of 32 cameras with presets."""
        self.login(self.admin_user, self.admin_pass)
        res = self.client.get("/api/admin/cameras/all")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 32)
        self.assertIn("presets", data)
        self.assertIn("lobby", data["presets"])
        self.assertIn("office", data["presets"])
        cam11 = next(c for c in data["cameras"] if c["channel"] == 11)
        self.assertIn("11.T1. QUẢN LÝ HSSV", cam11["name"])

    def test_security_active_sessions_and_audit(self):
        """Admin can monitor active sessions and audit logs."""
        self.login(self.admin_user, self.admin_pass)
        res = self.client.get("/api/admin/security/active-sessions")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(any(s["username"] == self.admin_user for s in data["sessions"]))

        audit_res = self.client.get("/api/admin/security/audit-logs")
        self.assertEqual(audit_res.status_code, 200)
        logs = audit_res.json()["logs"]
        self.assertTrue(len(logs) > 0)
        self.assertEqual(logs[0]["status"], "success")

    def test_security_lockouts_and_unblock(self):
        """Admin can inspect locked entities and unblock them."""
        self.login(self.admin_user, self.admin_pass)
        res = self.client.get("/api/admin/security/lockouts")
        self.assertEqual(res.status_code, 200)

        unblock_res = self.client.post("/api/admin/security/unblock", json={"target": "192.168.1.99"})
        self.assertEqual(unblock_res.status_code, 200)
        self.assertEqual(unblock_res.json()["status"], "success")

    def test_admin_user_crud_with_channels(self):
        """Admin can create, update, and delete user with specific channel matrix."""
        self.login(self.admin_user, self.admin_pass)
        create_res = self.client.post("/api/admin/users", json={
            "username": "guard_lobby",
            "password": "GuardPassword123@",
            "full_name": "Bảo vệ Sảnh",
            "role": "viewer",
            "allowed_channels": [18, 19, 20]
        })
        self.assertEqual(create_res.status_code, 200)

        update_res = self.client.put("/api/admin/users/guard_lobby", json={
            "full_name": "Bảo vệ Sảnh & HSSV",
            "role": "operator",
            "allowed_channels": [11, 18, 19, 20]
        })
        self.assertEqual(update_res.status_code, 200)

        users_res = self.client.get("/api/admin/users")
        guard = next(u for u in users_res.json() if u["username"] == "guard_lobby")
        self.assertEqual(guard["role"], "operator")
        self.assertEqual(sorted(guard["allowed_channels"]), [11, 18, 19, 20])

        del_res = self.client.delete("/api/admin/users/guard_lobby")
        self.assertEqual(del_res.status_code, 200)

    def test_new_user_default_channels_strictly_18_and_19(self):
        """Newly created accounts without channels specified must default to strictly [18, 19]."""
        self.login(self.admin_user, self.admin_pass)
        create_res = self.client.post("/api/admin/users", json={
            "username": "new_staff_member",
            "password": "Password789@",
            "full_name": "Nhân viên mới",
            "role": "viewer"
        })
        self.assertEqual(create_res.status_code, 200)

        users_res = self.client.get("/api/admin/users")
        new_user = next(u for u in users_res.json() if u["username"] == "new_staff_member")
        self.assertEqual(sorted(new_user["allowed_channels"]), [18, 19])

        # Test Google SSO new user upsert defaults to strictly [18, 19]
        google_user = main.upsert_google_system_user("new_google_user@nctu.edu.vn", "Google Staff", "", False)
        self.assertEqual(sorted(google_user["allowed_channels"]), [18, 19])


if __name__ == "__main__":
    unittest.main()

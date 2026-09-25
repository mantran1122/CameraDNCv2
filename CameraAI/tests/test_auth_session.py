import unittest

from fastapi.testclient import TestClient

import main


class AuthenticationSessionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()

    def test_private_pages_and_apis_require_login(self):
        page = self.client.get("/search", follow_redirects=False)
        api = self.client.get("/api/events")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["location"], "/login")
        self.assertEqual(api.status_code, 401)

    def test_verified_login_sets_session_and_logout_clears_it(self):
        username, password = main.get_admin_credentials()
        response = self.client.post(
            "/api/admin/verify-login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("cameraai_session", response.cookies)
        self.assertEqual(self.client.get("/search").status_code, 200)

        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/search", follow_redirects=False).status_code, 302)

    def test_invalid_login_does_not_create_session(self):
        response = self.client.post(
            "/api/admin/verify-login",
            json={"username": "invalid", "password": "invalid"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("cameraai_session", response.cookies)

    def test_security_headers_present_on_responses(self):
        response = self.client.get("/login")
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(response.headers.get("x-frame-options"), "DENY")
        self.assertEqual(response.headers.get("x-xss-protection"), "1; mode=block")
        self.assertEqual(response.headers.get("referrer-policy"), "strict-origin-when-cross-origin")

    def test_websocket_requires_authentication(self):
        from starlette.websockets import WebSocketDisconnect

        # Unauthenticated attempt should be rejected with code 1008
        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect("/ws"):
                pass
        self.assertEqual(cm.exception.code, 1008)

        # Authenticated attempt should succeed
        username, password = main.get_admin_credentials()
        login_resp = self.client.post(
            "/api/admin/verify-login",
            json={"username": username, "password": password},
        )
        self.assertEqual(login_resp.status_code, 200)

        with self.client.websocket_connect("/ws") as ws:
            ws.send_text("test_ping")


if __name__ == "__main__":
    unittest.main()

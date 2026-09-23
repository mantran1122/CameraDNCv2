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


if __name__ == "__main__":
    unittest.main()

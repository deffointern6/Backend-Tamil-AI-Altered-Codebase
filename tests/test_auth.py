import unittest
import os
from fastapi.testclient import TestClient
from settings.config import settings

# Setup test environment before importing database modules
settings.database_url = "sqlite:///./test.db"

from database.db import Base, SessionLocal, engine
from database.models_db import User, Job, Account
from main import app

class TestAuthAndMiddleware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)

    def setUp(self):
        # Clear tables between tests
        db = SessionLocal()
        try:
            db.query(User).delete()
            db.query(Job).delete()
            db.query(Account).delete()
            db.commit()
        finally:
            db.close()

    def test_registration_and_login_flow(self):
        # 1. Register User
        reg_payload = {
            "username": "tester",
            "email": "tester@example.com",
            "password": "securepassword"
        }
        response = self.client.post("/auth/register", json=reg_payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["username"], "tester")
        self.assertEqual(data["email"], "tester@example.com")
        self.assertTrue(data["is_active"])
        self.assertNotIn("password", data)
        self.assertNotIn("hashed_password", data)

        # Register same username should fail
        response = self.client.post("/auth/register", json=reg_payload)
        self.assertEqual(response.status_code, 400)

        # 2. Login User (JSON)
        login_payload = {
            "username": "tester",
            "password": "securepassword"
        }
        response = self.client.post("/auth/login", json=login_payload)
        self.assertEqual(response.status_code, 200)
        token_data = response.json()
        self.assertIn("access_token", token_data)
        self.assertIn("refresh_token", token_data)
        self.assertEqual(token_data["token_type"], "bearer")
        token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]

        # Login User with wrong password
        login_payload["password"] = "wrongpassword"
        response = self.client.post("/auth/login", json=login_payload)
        self.assertEqual(response.status_code, 401)

        # 3. Access /auth/me
        headers = {"Authorization": f"Bearer {token}"}
        response = self.client.get("/auth/me", headers=headers)
        self.assertEqual(response.status_code, 200)
        user_data = response.json()
        self.assertEqual(user_data["username"], "tester")
        self.assertEqual(user_data["email"], "tester@example.com")

        # Access /auth/me with invalid token
        response = self.client.get("/auth/me", headers={"Authorization": "Bearer invalidtoken"})
        self.assertEqual(response.status_code, 401)

        # 4. Refresh token flow (valid)
        refresh_response = self.client.post("/auth/refresh", json={"refresh_token": refresh_token})
        self.assertEqual(refresh_response.status_code, 200)
        refresh_data = refresh_response.json()
        self.assertIn("access_token", refresh_data)
        self.assertIn("refresh_token", refresh_data)
        new_access_token = refresh_data["access_token"]
        new_refresh_token = refresh_data["refresh_token"]

        # Verify old token has been revoked / rotated
        revoked_response = self.client.post("/auth/refresh", json={"refresh_token": refresh_token})
        self.assertEqual(revoked_response.status_code, 401)

        # 5. Logout flow
        logout_response = self.client.post("/auth/logout", json={"refresh_token": new_refresh_token})
        self.assertEqual(logout_response.status_code, 200)
        
        # Verify logged out token cannot be refreshed
        ref_after_logout = self.client.post("/auth/refresh", json={"refresh_token": new_refresh_token})
        self.assertEqual(ref_after_logout.status_code, 401)

    def test_oauth2_form_token_route(self):
        # Register user first
        reg_payload = {
            "username": "oauthuser",
            "email": "oauth@example.com",
            "password": "oauthpassword"
        }
        response = self.client.post("/auth/register", json=reg_payload)
        self.assertEqual(response.status_code, 201)

        # Login using form fields
        form_data = {
            "username": "oauthuser",
            "password": "oauthpassword"
        }
        response = self.client.post("/auth/token", data=form_data)
        self.assertEqual(response.status_code, 200)
        token_data = response.json()
        self.assertIn("access_token", token_data)
        self.assertIn("refresh_token", token_data)
        self.assertEqual(token_data["token_type"], "bearer")

    def test_rate_limiting_middleware(self):
        # Register & Login
        reg_payload = {
            "username": "limiter_user",
            "email": "limiter@example.com",
            "password": "limitpassword"
        }
        response = self.client.post("/auth/register", json=reg_payload)
        self.assertEqual(response.status_code, 201)

        login_payload = {
            "username": "limiter_user",
            "password": "limitpassword"
        }
        response = self.client.post("/auth/login", json=login_payload)
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Mock Redis Pipeline behavior to trigger 429
        from unittest.mock import patch, MagicMock
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [0, 1, 35, True]  # 35 exceeds the 30 limit
        mock_redis.pipeline.return_value = mock_pipe

        with patch("middleware.rate_limit_middleware.redis_conn", mock_redis):
            job_payload = {
                "model": "letter-gen",
                "input": "test input"
            }
            response = self.client.post("/jobs", json=job_payload, headers=headers)
            self.assertEqual(response.status_code, 429)
            data = response.json()
            self.assertEqual(data["detail"]["error"], "Rate limit exceeded")

    def test_account_profile_flow(self):
        # 1. Register a user
        reg_payload = {
            "username": "profile_tester",
            "email": "profile@example.com",
            "password": "profilepassword"
        }
        response = self.client.post("/auth/register", json=reg_payload)
        self.assertEqual(response.status_code, 201)

        # 2. Login to get access token
        login_payload = {
            "username": "profile_tester",
            "password": "profilepassword"
        }
        response = self.client.post("/auth/login", json=login_payload)
        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Retrieve account profile (automatically created on register)
        response = self.client.get("/auth/account", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["username"], "profile_tester")
        self.assertEqual(data["email"], "profile@example.com")
        self.assertEqual(data["display_name"], "profile_tester")
        self.assertEqual(data["phone_number"], "")
        self.assertEqual(data["dob"], "")

        # 4. Update the account profile (using YYYY-MM-DD format for DOB)
        update_payload = {
            "display_name": "Updated Display",
            "phone_number": "+1234567890",
            "dob": "1995-12-25"
        }
        response = self.client.put("/auth/account", json=update_payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["display_name"], "Updated Display")
        self.assertEqual(data["phone_number"], "+1234567890")
        # Ensure it got normalized to dd/mm/yyyy format in the response (and thus in the DB)
        self.assertEqual(data["dob"], "25/12/1995")

        # 5. Retrieve again to make sure it matches
        response = self.client.get("/auth/account", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["display_name"], "Updated Display")
        self.assertEqual(data["phone_number"], "+1234567890")
        self.assertEqual(data["dob"], "25/12/1995")

        # 6. Test direct dd/mm/yyyy update
        update_payload = {
            "dob": "01/01/2000"
        }
        response = self.client.put("/auth/account", json=update_payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dob"], "01/01/2000")

        # 7. Test invalid DOB format
        update_payload = {
            "dob": "invalid-date"
        }
        response = self.client.put("/auth/account", json=update_payload, headers=headers)
        self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    unittest.main()

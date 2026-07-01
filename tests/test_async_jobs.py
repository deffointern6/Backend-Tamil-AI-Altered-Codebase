import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup test environment before importing database modules
import os
from settings.config import settings
settings.database_url = "sqlite:///./test.db"

from database.db import Base, SessionLocal, engine
from database.models_db import Job, User
from database.jobs import get_job, create_job
from main import app
from worker import run_job
from auth.hash import hash_password
from auth.jwt import create_access_token

class TestAsyncJobs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Create tables
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        # Cleanup test database tables
        Base.metadata.drop_all(bind=engine)

    def setUp(self):
        # Clear tables between tests
        db = SessionLocal()
        try:
            db.query(Job).delete()
            db.query(User).delete()
            db.commit()
            
            # Create a test user for authenticated requests
            self.test_user = User(
                username="testuser",
                email="testuser@example.com",
                hashed_password=hash_password("password123"),
                is_active=True
            )
            db.add(self.test_user)
            db.commit()
            db.refresh(self.test_user)
            
            # Generate JWT token
            token = create_access_token(data={"sub": self.test_user.username})
            self.headers = {"Authorization": f"Bearer {token}"}
        finally:
            db.close()

    @patch("api.jobs.default_queue")
    @patch("api.jobs.high_queue")
    def test_post_job_creates_db_record_and_enqueues(self, mock_high_queue, mock_default_queue):
        payload = {
            "model": "letter-gen",
            "input": "I need a leave letter"
        }
        
        response = self.client.post("/jobs", json=payload, headers=self.headers)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("job_id", data)
        self.assertEqual(data["status"], "queued")
        
        job_id = data["job_id"]
        
        # Verify database record exists
        job = get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.user_id, self.test_user.id)
        self.assertEqual(job.model, "letter-gen")
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.input, "I need a leave letter")
        
        # Verify enqueued into default Redis queue
        from unittest.mock import ANY
        mock_default_queue.enqueue.assert_called_once_with("worker.run_job", job_id, ANY, job_timeout=600)
        mock_high_queue.enqueue.assert_not_called()

    def test_post_unknown_model_returns_404(self):
        payload = {
            "model": "unknown-nonexistent-model",
            "input": "test input"
        }
        response = self.client.post("/jobs", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 404)

    @patch("worker.log_metric")
    @patch("worker.is_space_sleeping")
    @patch("worker.get_model")
    @patch("worker.parse_model_output")
    def test_worker_runs_successfully(self, mock_parse, mock_get_model, mock_is_sleeping, mock_log_metric):
        mock_is_sleeping.return_value = False
        
        # Mock adapter
        mock_adapter = MagicMock()
        mock_adapter.run.return_value = "raw output"
        mock_get_model.return_value = mock_adapter
        
        # Mock clean parser
        mock_parse.return_value = {"letter": "Parsed Leave Letter Content"}
        
        # Create a queued job in DB
        job_id = create_job(user_id="test-user", model="letter-gen", input_data="I need a leave letter")
        
        # Run worker function
        run_job(job_id)
        
        # Verify job is done and result is saved
        job = get_job(job_id)
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result, {"letter": "Parsed Leave Letter Content"})
        self.assertIsNone(job.error)
        
        # Verify log_metric was called
        mock_log_metric.assert_called_once()

    @patch("worker.log_metric")
    @patch("worker.is_space_sleeping")
    @patch("worker.get_model")
    def test_worker_fails_and_saves_error(self, mock_get_model, mock_is_sleeping, mock_log_metric):
        mock_is_sleeping.return_value = False
        
        # Mock adapter to throw exception
        mock_adapter = MagicMock()
        mock_adapter.run.side_effect = RuntimeError("HF connection timeout")
        mock_get_model.return_value = mock_adapter
        
        job_id = create_job(user_id="test-user", model="letter-gen", input_data="I need a leave letter")
        
        # Run worker (it will raise Exception, which we catch in test assert)
        with self.assertRaises(RuntimeError):
            run_job(job_id)
            
        # Verify job is set to error in DB
        job = get_job(job_id)
        self.assertEqual(job.status, "error")
        self.assertIn("HF connection timeout", job.error)
        self.assertIsNone(job.result)
        
        # Verify log_metric was called
        mock_log_metric.assert_called_once()

if __name__ == '__main__':
    unittest.main()

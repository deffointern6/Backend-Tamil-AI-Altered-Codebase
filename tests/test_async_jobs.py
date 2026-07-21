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
        mock_default_queue.enqueue.assert_called_once_with("worker.run_job", job_id, ANY, job_timeout=90, retry=ANY)
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

    def test_post_job_exceeds_character_limit(self):
        payload = {
            "model": "tongue-twister",
            "input": "a" * 201  # Limit is 200
        }
        response = self.client.post("/jobs", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 413)
        # Verify validation message contains the limit error
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("limit", data["detail"])

    def test_post_job_exceeds_user_concurrency_limit(self):
        # Create 10 active jobs in DB for the test user
        db = SessionLocal()
        try:
            for _ in range(10):
                job = Job(
                    user_id=self.test_user.id,
                    model="letter-gen",
                    status="running",
                    input="some input"
                )
                db.add(job)
            db.commit()
        finally:
            db.close()
            
        # Now submit an 11th job
        payload = {
            "model": "letter-gen",
            "input": "eleventh job input"
        }
        response = self.client.post("/jobs", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 429)
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("Maximum concurrent jobs limit reached", data["detail"])

    def test_evaluate_mcq_success_list_strings(self):
        db = SessionLocal()
        try:
            job = Job(
                user_id=self.test_user.id,
                model="mcq-gen",
                status="done",
                input="dummy input",
                result=[
                    {"question": "Q1", "options": ["A", "B"], "answer": "A"},
                    {"question": "Q2", "options": ["C", "D"], "answer": "D"}
                ]
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        payload = {"answers": ["A", "C"]} # 1 correct, 1 incorrect
        response = self.client.post(f"/jobs/{job_id}/evaluate", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["job_id"], job_id)
        self.assertEqual(data["score"], 1)
        self.assertEqual(data["total_questions"], 2)
        self.assertEqual(len(data["evaluation"]), 2)
        self.assertEqual(data["evaluation"][0]["is_correct"], True)
        self.assertEqual(data["evaluation"][1]["is_correct"], False)

    def test_evaluate_mcq_success_list_dicts(self):
        db = SessionLocal()
        try:
            job = Job(
                user_id=self.test_user.id,
                model="mcq-gen",
                status="done",
                input="dummy input",
                result=[
                    {"question": "Q1", "options": ["A", "B"], "answer": "A"}
                ]
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        payload = {
            "answers": [
                {"question_index": 0, "selected_option": "A"}
            ]
        }
        response = self.client.post(f"/jobs/{job_id}/evaluate", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["score"], 1)
        self.assertEqual(data["evaluation"][0]["selected_option"], "A")

    def test_evaluate_mcq_success_dict(self):
        db = SessionLocal()
        try:
            job = Job(
                user_id=self.test_user.id,
                model="mcq-gen",
                status="done",
                input="dummy input",
                result=[
                    {"question": "Q1", "options": ["A", "B"], "answer": "A"}
                ]
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        payload = {
            "answers": {"0": "B"}
        }
        response = self.client.post(f"/jobs/{job_id}/evaluate", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["score"], 0)
        self.assertEqual(data["evaluation"][0]["is_correct"], False)

    def test_evaluate_mcq_unanswered_questions(self):
        db = SessionLocal()
        try:
            job = Job(
                user_id=self.test_user.id,
                model="mcq-gen",
                status="done",
                input="dummy input",
                result=[
                    {"question": "Q1", "options": ["A", "B"], "answer": "A"},
                    {"question": "Q2", "options": ["C", "D"], "answer": "D"}
                ]
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        payload = {"answers": ["A"]}  # only 1 answer provided
        response = self.client.post(f"/jobs/{job_id}/evaluate", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["score"], 1)
        self.assertEqual(data["evaluation"][1]["selected_option"], None)
        self.assertEqual(data["evaluation"][1]["is_correct"], False)

    def test_evaluate_mcq_job_not_found(self):
        payload = {"answers": ["A"]}
        response = self.client.post("/jobs/nonexistent-uuid/evaluate", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_evaluate_mcq_unauthorized(self):
        db = SessionLocal()
        try:
            job = Job(
                user_id="other-user-id",
                model="mcq-gen",
                status="done",
                input="dummy input",
                result=[{"question": "Q1", "options": ["A", "B"], "answer": "A"}]
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        payload = {"answers": ["A"]}
        response = self.client.post(f"/jobs/{job_id}/evaluate", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 403)

    def test_evaluate_mcq_wrong_model(self):
        db = SessionLocal()
        try:
            job = Job(
                user_id=self.test_user.id,
                model="letter-gen",
                status="done",
                input="dummy input",
                result={"letter": "some letter"}
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        payload = {"answers": ["A"]}
        response = self.client.post(f"/jobs/{job_id}/evaluate", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only mcq-gen jobs can be evaluated", response.json()["detail"])

    def test_evaluate_mcq_not_done(self):
        db = SessionLocal()
        try:
            job = Job(
                user_id=self.test_user.id,
                model="mcq-gen",
                status="running",
                input="dummy input",
                result=None
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        payload = {"answers": ["A"]}
        response = self.client.post(f"/jobs/{job_id}/evaluate", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Job is not completed yet", response.json()["detail"])

if __name__ == '__main__':
    unittest.main()

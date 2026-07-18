import unittest
import json
import datetime
import time
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from settings.config import settings
# Setup test environment before importing database modules
settings.database_url = "sqlite:///./test.db"

from database.db import Base, SessionLocal, engine
from database.models_db import User, Account
from utils.metrics import log_metric, calculate_metrics, read_metrics_records, REDIS_METRICS_KEY
from main import app

class TestMetrics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)

    def setUp(self):
        # Clear tables
        db = SessionLocal()
        try:
            db.query(User).delete()
            db.query(Account).delete()
            db.commit()
        finally:
            db.close()

        # Mock Redis store in memory
        self.redis_store = {}
        self.mock_redis = MagicMock()
        
        # Simulates Redis zadd
        def mock_zadd(key, mapping):
            self.redis_store.setdefault(key, [])
            for member, score in mapping.items():
                # Avoid duplicates in mock
                self.redis_store[key] = [x for x in self.redis_store[key] if x[0] != member]
                self.redis_store[key].append((member, score))
            # Keep sorted by score
            self.redis_store[key].sort(key=lambda x: x[1])
            return len(mapping)
        self.mock_redis.zadd.side_effect = mock_zadd
        
        # Simulates Redis zrange
        def mock_zrange(key, start, end):
            if key not in self.redis_store:
                return []
            items = [item[0] for item in self.redis_store[key]]
            # Convert to bytes as live Redis does
            return [i.encode("utf-8") if isinstance(i, str) else i for i in items]
        self.mock_redis.zrange.side_effect = mock_zrange
        
        # Simulates Redis zremrangebyscore
        def mock_zremrange(key, min_score, max_score):
            if key not in self.redis_store:
                return 0
            original_len = len(self.redis_store[key])
            self.redis_store[key] = [x for x in self.redis_store[key] if x[1] > max_score]
            return original_len - len(self.redis_store[key])
        self.mock_redis.zremrangebyscore.side_effect = mock_zremrange
        
        # Patch the global redis_conn in utils.metrics
        self.patcher = patch("utils.metrics.redis_conn", self.mock_redis)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_log_metric(self):
        log_metric("letter-gen", 1.5, True, queue_wait_time=0.2, wake_up_delay=1.0)
        
        records = read_metrics_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["model_name"], "letter-gen")
        self.assertEqual(records[0]["latency"], 1.5)
        self.assertEqual(records[0]["success"], True)
        self.assertEqual(records[0]["queue_wait_time"], 0.2)
        self.assertEqual(records[0]["wake_up_delay"], 1.0)
        self.assertIn("timestamp", records[0])

    @patch("utils.metrics.get_queue_depth")
    def test_calculate_metrics(self, mock_get_queue_depth):
        mock_get_queue_depth.return_value = 5
        
        # Write mock records directly to the in-memory Redis mock
        now = datetime.datetime.utcnow()
        records = [
            {"timestamp": (now - datetime.timedelta(seconds=10)).isoformat(), "model_name": "letter-gen", "latency": 1.0, "success": True, "queue_wait_time": 0.1, "wake_up_delay": 0.0},
            {"timestamp": (now - datetime.timedelta(seconds=20)).isoformat(), "model_name": "letter-gen", "latency": 2.0, "success": True, "queue_wait_time": 0.2, "wake_up_delay": 0.0},
            {"timestamp": (now - datetime.timedelta(seconds=30)).isoformat(), "model_name": "letter-gen", "latency": 3.0, "success": True, "queue_wait_time": 0.3, "wake_up_delay": 0.0},
            {"timestamp": (now - datetime.timedelta(seconds=40)).isoformat(), "model_name": "letter-gen", "latency": 1.5, "success": False, "queue_wait_time": 0.4, "wake_up_delay": 0.0},
            {"timestamp": (now - datetime.timedelta(minutes=10)).isoformat(), "model_name": "poem-gen", "latency": 5.0, "success": True, "queue_wait_time": 0.5, "wake_up_delay": 3.0},
        ]
        
        for r in records:
            dt = datetime.datetime.fromisoformat(r["timestamp"])
            score = dt.timestamp()
            self.mock_redis.zadd(REDIS_METRICS_KEY, {json.dumps(r): score})
                
        metrics = calculate_metrics()
        
        # Verify queue depth
        self.assertEqual(metrics["queue_depth"], 5)
        
        # Verify 1 min stats (excludes poem-gen)
        last_1_min = metrics["last_1_min"]
        self.assertEqual(last_1_min["total_requests"], 4)
        self.assertEqual(last_1_min["failed_requests"]["total"], 1)
        self.assertEqual(last_1_min["requests_per_model"]["letter-gen"], 4)
        # Latencies for letter-gen: 1.0, 2.0, 3.0. P95 index: sorted [1.0, 2.0, 3.0] -> index 2 is 3.0
        self.assertEqual(last_1_min["p95_latency_per_model"]["letter-gen"], 3.0)
        
        # Verify 1 hour stats (includes poem-gen)
        last_1_hour = metrics["last_1_hour"]
        self.assertEqual(last_1_hour["total_requests"], 5)
        self.assertEqual(last_1_hour["space_wake_up_delays"]["poem-gen"]["count"], 1)
        self.assertEqual(last_1_hour["space_wake_up_delays"]["poem-gen"]["total_delay_seconds"], 3.0)

    @patch("utils.metrics.get_queue_depth")
    def test_api_endpoints(self, mock_get_queue_depth):
        mock_get_queue_depth.return_value = 2
        
        # Write one mock record
        now = datetime.datetime.utcnow()
        record = {"timestamp": now.isoformat(), "model_name": "letter-gen", "latency": 1.2, "success": True, "queue_wait_time": 0.1, "wake_up_delay": 0.0}
        self.mock_redis.zadd(REDIS_METRICS_KEY, {json.dumps(record): now.timestamp()})
            
        client = TestClient(app)
        
        # Check summary and raw endpoints fail without auth (401)
        response = client.get("/metrics/summary")
        self.assertEqual(response.status_code, 401)
        response = client.get("/metrics/raw?limit=10")
        self.assertEqual(response.status_code, 401)

        # Register a test user
        reg_payload = {
            "username": "metricstester",
            "email": "metrics@example.com",
            "password": "metricspassword"
        }
        client.post("/auth/register", json=reg_payload)

        # Login to get access token
        login_payload = {
            "username": "metricstester",
            "password": "metricspassword"
        }
        login_response = client.post("/auth/login", json=login_payload)
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Check summary endpoint with auth for regular user (non-admin should get 403)
        response = client.get("/metrics/summary", headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Access forbidden: Administrator privileges required.")
        
        # Check raw endpoint with auth for regular user (non-admin should get 403)
        response = client.get("/metrics/raw?limit=10", headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Access forbidden: Administrator privileges required.")

        # Promote user to admin in the test database
        db = SessionLocal()
        try:
            db_user = db.query(User).filter(User.username == "metricstester").first()
            db_user.is_admin = True
            db.commit()
        finally:
            db.close()

        # Check summary endpoint with auth for admin user (should get 200)
        response = client.get("/metrics/summary", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["queue_depth"], 2)
        self.assertEqual(data["last_5_min"]["total_requests"], 1)
        
        # Check raw endpoint with auth for admin user (should get 200)
        response = client.get("/metrics/raw?limit=10", headers=headers)
        self.assertEqual(response.status_code, 200)
        raw_data = response.json()
        self.assertEqual(len(raw_data), 1)
        self.assertEqual(raw_data[0]["model_name"], "letter-gen")

if __name__ == '__main__':
    unittest.main()

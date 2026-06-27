import unittest
import os
import json
import datetime
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Override METRICS_FILE path before importing to keep test directory clean
import utils.metrics
TEST_METRICS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
    "test_metrics.jsonl"
)
utils.metrics.METRICS_FILE = TEST_METRICS_FILE

from utils.metrics import log_metric, calculate_metrics, read_metrics_records
from main import app

class TestMetrics(unittest.TestCase):

    def setUp(self):
        # Clean up test metrics file before each test
        if os.path.exists(TEST_METRICS_FILE):
            try:
                os.remove(TEST_METRICS_FILE)
            except OSError:
                pass

    def tearDown(self):
        # Clean up test metrics file after each test
        if os.path.exists(TEST_METRICS_FILE):
            try:
                os.remove(TEST_METRICS_FILE)
            except OSError:
                pass

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
        
        # Write mock records directly
        now = datetime.datetime.utcnow()
        records = [
            {"timestamp": (now - datetime.timedelta(seconds=10)).isoformat(), "model_name": "letter-gen", "latency": 1.0, "success": True, "queue_wait_time": 0.1, "wake_up_delay": 0.0},
            {"timestamp": (now - datetime.timedelta(seconds=20)).isoformat(), "model_name": "letter-gen", "latency": 2.0, "success": True, "queue_wait_time": 0.2, "wake_up_delay": 0.0},
            {"timestamp": (now - datetime.timedelta(seconds=30)).isoformat(), "model_name": "letter-gen", "latency": 3.0, "success": True, "queue_wait_time": 0.3, "wake_up_delay": 0.0},
            {"timestamp": (now - datetime.timedelta(seconds=40)).isoformat(), "model_name": "letter-gen", "latency": 1.5, "success": False, "queue_wait_time": 0.4, "wake_up_delay": 0.0},
            {"timestamp": (now - datetime.timedelta(minutes=10)).isoformat(), "model_name": "poem-gen", "latency": 5.0, "success": True, "queue_wait_time": 0.5, "wake_up_delay": 3.0},
        ]
        
        with open(TEST_METRICS_FILE, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
                
        metrics = calculate_metrics()
        
        # Verify queue depth
        self.assertEqual(metrics["queue_depth"], 5)
        
        # Verify 1 min stats (excludes poem-gen)
        last_1_min = metrics["last_1_min"]
        self.assertEqual(last_1_min["total_requests"], 4)
        self.assertEqual(last_1_min["failed_requests"]["total"], 1)
        self.assertEqual(last_1_min["requests_per_model"]["letter-gen"], 4)
        # Latencies for letter-gen: 1.0, 2.0, 3.0. P95 index for 3 elements: int(3 * 0.95) = 2. Sorted: [1.0, 2.0, 3.0] -> index 2 is 3.0
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
        with open(TEST_METRICS_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
            
        client = TestClient(app)
        
        # Check summary endpoint
        response = client.get("/metrics/summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["queue_depth"], 2)
        self.assertEqual(data["last_5_min"]["total_requests"], 1)
        
        # Check raw endpoint
        response = client.get("/metrics/raw?limit=10")
        self.assertEqual(response.status_code, 200)
        raw_data = response.json()
        self.assertEqual(len(raw_data), 1)
        self.assertEqual(raw_data[0]["model_name"], "letter-gen")

if __name__ == '__main__':
    unittest.main()

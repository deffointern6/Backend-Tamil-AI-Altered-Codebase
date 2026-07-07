import os
import json
import time
import datetime
from collections import defaultdict
import logging
from redis import Redis
from rq import Queue
from huggingface_hub import HfApi
from settings.config import settings

logger = logging.getLogger("metrics")

# Initialize Redis connection for metrics
try:
    redis_conn = Redis.from_url(settings.redis_url)
except Exception as e:
    logger.error(f"Failed to connect to Redis for metrics: {e}")
    redis_conn = None

# Key namespace for Redis metrics log
REDIS_METRICS_KEY = "metrics:raw_log"

# Keep legacy variable to prevent import breakages in tests
METRICS_FILE = "metrics.jsonl"

def log_metric(model_name: str, latency: float, success: bool, queue_wait_time: float = 0.0, wake_up_delay: float = 0.0):
    """
    Logs a single model execution metric into Redis Sorted Set.
    """
    if redis_conn is None:
        logger.error("Redis connection not available for logging metrics.")
        return

    try:
        record = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "model_name": model_name,
            "latency": latency,
            "success": success,
            "queue_wait_time": queue_wait_time,
            "wake_up_delay": wake_up_delay
        }
        now = time.time()
        # Add serialized JSON string to sorted set with timestamp score
        redis_conn.zadd(REDIS_METRICS_KEY, {json.dumps(record): now})
        
        # Keep only the last 24 hours of raw data to prevent Redis memory bloat
        one_day_ago = now - 86400
        redis_conn.zremrangebyscore(REDIS_METRICS_KEY, 0, one_day_ago)
    except Exception as e:
        logger.error(f"Failed to log metric for model {model_name}: {e}")


_SPACE_STATUS_CACHE = {}  # Cache map: space_id -> (is_sleeping, timestamp)

def is_space_sleeping(space_id: str) -> bool:
    """
    Checks if a Hugging Face space is sleeping or not running.
    Caches the status for 5 minutes (300 seconds) to avoid overhead on every request.
    """
    now = time.time()
    if space_id in _SPACE_STATUS_CACHE:
        cached_val, timestamp = _SPACE_STATUS_CACHE[space_id]
        if now - timestamp < 300:
            return cached_val

    try:
        api = HfApi(token=settings.hf_token)
        runtime = api.get_space_runtime(repo_id=space_id)
        # Runtime stages: RUNNING, SLEEPING, PAUSED, STOPPED, BUILDING, etc.
        is_sleeping = runtime.stage != "RUNNING"
        _SPACE_STATUS_CACHE[space_id] = (is_sleeping, now)
        return is_sleeping
    except Exception as e:
        logger.warning(f"Failed to check space status for {space_id}: {e}")
        return False


def get_queue_depth() -> int:
    """
    Retrieves the total number of jobs in both high and default RQ queues.
    """
    try:
        redis_url = settings.redis_url if settings.redis_url else "redis://localhost:6379/0"
        redis_conn = Redis.from_url(redis_url)
        high_q = Queue("high", connection=redis_conn)
        default_q = Queue("default", connection=redis_conn)
        return len(high_q) + len(default_q)
    except Exception as e:
        logger.warning(f"Failed to fetch queue depth from Redis: {e}")
        return -1


def read_metrics_records() -> list:
    """
    Reads and parses all records from the Redis Sorted Set.
    """
    if redis_conn is None:
        return []

    try:
        # Retrieve all items from Redis sorted set
        raw_items = redis_conn.zrange(REDIS_METRICS_KEY, 0, -1)
        records = []
        for item in raw_items:
            try:
                decoded = item.decode("utf-8") if isinstance(item, bytes) else item
                records.append(json.loads(decoded))
            except Exception:
                pass
        return records
    except Exception as e:
        logger.error(f"Failed to read metrics records from Redis: {e}")
        return []


def calculate_window_stats(records: list, start_time: datetime.datetime) -> dict:
    """
    Computes aggregates for records whose timestamp >= start_time.
    """
    # Grouped data
    requests_per_model = defaultdict(int)
    latencies_per_model = defaultdict(list)
    failures_per_model = defaultdict(int)
    wake_up_delays_per_model = defaultdict(list)
    total_requests = 0
    total_failures = 0

    for r in records:
        try:
            ts = datetime.datetime.fromisoformat(r["timestamp"])
        except Exception:
            continue

        if ts < start_time:
            continue

        model = r.get("model_name", "unknown")
        latency = r.get("latency", 0.0)
        success = r.get("success", True)
        wake_up_delay = r.get("wake_up_delay", 0.0)

        total_requests += 1
        requests_per_model[model] += 1

        if success:
            latencies_per_model[model].append(latency)
        else:
            failures_per_model[model] += 1
            total_failures += 1

        if wake_up_delay > 0:
            wake_up_delays_per_model[model].append(wake_up_delay)

    # Calculate P95 latency per model
    p95_latency = {}
    for model, lats in latencies_per_model.items():
        if not lats:
            p95_latency[model] = 0.0
            continue
        sorted_lats = sorted(lats)
        idx = int(len(sorted_lats) * 0.95)
        idx = min(idx, len(sorted_lats) - 1)
        p95_latency[model] = sorted_lats[idx]

    # Calculate space wake-up summary
    wake_up_summary = {}
    for model, delays in wake_up_delays_per_model.items():
        wake_up_summary[model] = {
            "count": len(delays),
            "total_delay_seconds": sum(delays),
            "avg_delay_seconds": sum(delays) / len(delays) if delays else 0.0,
            "max_delay_seconds": max(delays) if delays else 0.0
        }

    return {
        "total_requests": total_requests,
        "requests_per_model": dict(requests_per_model),
        "p95_latency_per_model": p95_latency,
        "failed_requests": {
            "total": total_failures,
            "per_model": dict(failures_per_model)
        },
        "space_wake_up_delays": wake_up_summary
    }


def calculate_metrics() -> dict:
    """
    Main metrics calculation engine returning sliding window aggregates.
    """
    records = read_metrics_records()
    now = datetime.datetime.utcnow()

    # Time boundaries
    one_min_ago = now - datetime.timedelta(minutes=1)
    five_min_ago = now - datetime.timedelta(minutes=5)
    one_hour_ago = now - datetime.timedelta(hours=1)
    twenty_four_hours_ago = now - datetime.timedelta(hours=24)

    return {
        "queue_depth": get_queue_depth(),
        "last_1_min": calculate_window_stats(records, one_min_ago),
        "last_5_min": calculate_window_stats(records, five_min_ago),
        "last_1_hour": calculate_window_stats(records, one_hour_ago),
        "last_24_hours": calculate_window_stats(records, twenty_four_hours_ago),
        "all_time": calculate_window_stats(records, datetime.datetime.min)
    }

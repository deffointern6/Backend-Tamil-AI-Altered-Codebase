import time
import logging
from fastapi import HTTPException, status, Request
from redis import Redis
from settings.config import settings

logger = logging.getLogger(__name__)

# Initialize Redis connection for rate limiting
try:
    redis_conn = Redis.from_url(settings.redis_url)
except Exception as e:
    logger.error(f"Failed to connect to Redis for rate limiting: {e}")
    redis_conn = None

# Model-specific rate limits defined as (limit, window_seconds)
MODEL_RATE_LIMITS = {
    "letter-gen": (30, 60),          # Heavy generation
    "email-gen": (40, 60),           # Medium
    "paraphrase-gen": (30, 60),      # Medium-heavy
    "tongue-twister": (100, 60),     # Very light
    "poem-gen": (30, 60),            # Generation
    "mcq-gen": (20, 60),             # Heavy processing
    "proofreader": (100, 60),        # Usually fast
    "default": (30, 60)
}

def check_rate_limit(user_id: str, model_name: str):
    """
    Enforces a model-specific rate limit using a sliding window in Redis.
    If Redis is unavailable, rate limiting is skipped (fail-open).
    """
    if redis_conn is None:
        return

    limit, window_seconds = MODEL_RATE_LIMITS.get(model_name, MODEL_RATE_LIMITS["default"])
    key = f"rate_limit:user:{user_id}:model:{model_name}"
    
    now = time.time()
    clear_before = now - window_seconds

    try:
        # Sliding window counter using Redis sorted sets
        pipe = redis_conn.pipeline()
        pipe.zremrangebyscore(key, 0, clear_before)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        
        # Execute pipeline
        _, _, current_count, _ = pipe.execute()
        
        if current_count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "message": f"Maximum {limit} executions for '{model_name}' allowed per {window_seconds} seconds.",
                    "retry_after": int(window_seconds - (now - clear_before))
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        # Fail-open
        logger.error(f"Rate limiter Redis error: {e}")
        return


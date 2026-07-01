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
    "letter-gen": (10, 60),
    "paraphrase-gen": (15, 60),
    "mcq-gen": (5, 60),
    "tongue-twister": (20, 60),
    "poem-gen": (5, 60),
    "email-gen": (10, 60),
    "proofreader": (30, 60),
    "default": (10, 60)
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


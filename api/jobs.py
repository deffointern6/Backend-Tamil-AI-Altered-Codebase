import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, model_validator
from redis import Redis
from rq import Queue
from settings.config import settings
from database.jobs import create_job, get_job
from database.db import get_db
from sqlalchemy.orm import Session
from services.registry import LIVE_TEXT_SPACES
from typing import Any

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Setup Redis connection and RQ Queues
redis_url = settings.redis_url if settings.redis_url else "redis://localhost:6379/0"
redis_conn = Redis.from_url(redis_url)
high_queue = Queue("high", connection=redis_conn)
default_queue = Queue("default", connection=redis_conn)


# --- REQUEST MODELS ---
class JobRequest(BaseModel):
    model: str = "letter-gen"
    input: Any

    @model_validator(mode="before")
    @classmethod
    def validate_input(cls, data):
        if isinstance(data, dict):
            if "input" not in data and "user_text" in data:
                data["input"] = data["user_text"]
            if "model" not in data:
                data["model"] = "letter-gen"
        return data


# --- POST ROUTE ---
@router.post("")
def run_model(request: JobRequest, db: Session = Depends(get_db)):
    logger.info(f"[JOB SUBMIT] Received request for model '{request.model}'")

    # Validate model exists in registry
    if request.model not in LIVE_TEXT_SPACES:
        logger.warning(f"[JOB SUBMIT] Model '{request.model}' not found in registry.")
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found")

    try:
        # Create job record in DB
        job_id = create_job(user_id="test-user", model=request.model, input_data=request.input, db=db)
        logger.info(f"[JOB SUBMIT] Created job {job_id} in database (status: queued)")

        # Enqueue job to Redis Queue
        # We pass task as string "worker.run_job" to avoid circular imports in RQ worker/API threads
        import time
        target_queue = high_queue if request.model in ["proofreader", "tongue-twister"] else default_queue
        target_queue.enqueue("worker.run_job", job_id, time.time(), job_timeout=600)
        logger.info(f"[JOB SUBMIT] Enqueued job {job_id} into '{target_queue.name}' Redis queue.")

        return {
            "job_id": job_id,
            "status": "queued"
        }
    except Exception as e:
        logger.exception(f"[JOB SUBMIT] Failed to submit job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


# --- GET ROUTE ---
@router.get("/{job_id}")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    logger.info(f"[JOB STATUS] Checking status for job {job_id}")
    job = get_job(job_id, db=db)
    if not job:
        logger.warning(f"[JOB STATUS] Job {job_id} not found in database.")
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.id,
        "status": job.status,
        "result": job.result,
        "error": job.error
    }
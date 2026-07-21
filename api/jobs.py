import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, model_validator
from redis import Redis
from rq import Queue, Retry
from settings.config import settings
from database.jobs import create_job, get_job
from database.db import get_db
from sqlalchemy.orm import Session
from services.registry import LIVE_TEXT_SPACES, MODEL_CHAR_LIMITS
from typing import Any
from auth.dependencies import get_current_user
from database.models_db import User, Job
from middleware.rate_limit_middleware import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Setup Redis connection and RQ Queues
redis_url = settings.redis_url if settings.redis_url else "redis://localhost:6379/0"
redis_conn = Redis.from_url(redis_url)
high_queue = Queue("high", connection=redis_conn)
default_queue = Queue("default", connection=redis_conn)

def clean_whitespace(val: Any) -> Any:
    if isinstance(val, str):
        return val.strip()
    elif isinstance(val, dict):
        return {k: clean_whitespace(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [clean_whitespace(item) for item in val]
    return val


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
            if "input" in data:
                data["input"] = clean_whitespace(data["input"])
        return data

    @model_validator(mode="after")
    def check_char_limit(self) -> "JobRequest":
        limit = MODEL_CHAR_LIMITS.get(self.model, MODEL_CHAR_LIMITS["default"])
        
        # Determine the length of the user input depending on the type
        text_to_check = ""
        if isinstance(self.input, str):
            text_to_check = self.input
        elif isinstance(self.input, dict):
            # Extract input text from common dictionary fields
            text_to_check = self.input.get("prompt", "") or \
                            self.input.get("user_text", "") or \
                            self.input.get("user_request", "") or \
                            self.input.get("answer", "") or \
                            self.input.get("text", "") or \
                            self.input.get("word", "") or ""
            # Fallback to total string representation if keys not found
            if not text_to_check:
                text_to_check = str(self.input)
        else:
            text_to_check = str(self.input)
            
        if not text_to_check or not text_to_check.strip():
            raise ValueError("Input text cannot be empty.")

        if len(text_to_check) > limit:
            raise ValueError(f"Input text exceeds the maximum limit of {limit} characters for model '{self.model}'.")
            
        return self


# --- QUEUE BACK-PRESSURE CONFIGURATION ---
MAX_QUEUE_DEPTH = 50  # Reject new jobs when the queue has this many pending items


# --- POST ROUTE ---
@router.post("")
def run_model(
    request: JobRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    logger.info(f"[JOB SUBMIT] Received request for model '{request.model}' from user '{current_user.username}'")

    # Enforce model-specific rate limiting
    check_rate_limit(user_id=current_user.id, model_name=request.model)

    # Validate model exists in registry
    if request.model not in LIVE_TEXT_SPACES:
        logger.warning(f"[JOB SUBMIT] Model '{request.model}' not found in registry.")
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found")

    # Back-pressure: reject requests when the job queue is overloaded
    try:
        queue_depth = len(high_queue) + len(default_queue)
        if queue_depth >= MAX_QUEUE_DEPTH:
            logger.warning(f"[JOB SUBMIT] Queue depth {queue_depth} exceeds limit {MAX_QUEUE_DEPTH}. Rejecting request.")
            raise HTTPException(
                status_code=503,
                detail=f"Server is busy processing {queue_depth} pending jobs. Please retry in a few seconds."
            )
    except HTTPException:
        raise
    except Exception as e:
        # Fail-open: if we can't check queue depth (Redis issue), allow the request through
        logger.error(f"[JOB SUBMIT] Failed to check queue depth: {e}")

    # Enforce maximum concurrent active jobs per user
    active_jobs = db.query(Job).filter(
        Job.user_id == current_user.id,
        Job.status.in_(["queued", "running"])
    ).count()
    if active_jobs >= 10:
        logger.warning(f"[JOB SUBMIT] User '{current_user.username}' exceeded concurrent job limit (active: {active_jobs}).")
        raise HTTPException(
            status_code=429,
            detail="Maximum concurrent jobs limit reached (limit: 10). Please wait for your other jobs to finish."
        )

    try:
        # Create job record in DB
        job_id = create_job(user_id=current_user.id, model=request.model, input_data=request.input, db=db)
        logger.info(f"[JOB SUBMIT] Created job {job_id} in database (status: queued)")

        # Enqueue job to Redis Queue with auto-retry and a shortened timeout of 90 seconds
        # We pass task as string "worker.run_job" to avoid circular imports in RQ worker/API threads
        import time
        target_queue = high_queue if request.model in ["proofreader", "tongue-twister"] else default_queue
        target_queue.enqueue(
            "worker.run_job", 
            job_id, 
            time.time(), 
            job_timeout=90,
            retry=Retry(max=3, interval=[2, 5, 10])
        )
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
def get_job_status(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    logger.info(f"[JOB STATUS] Checking status for job {job_id} by user {current_user.username}")
    job = get_job(job_id, db=db)
    if not job:
        logger.warning(f"[JOB STATUS] Job {job_id} not found in database.")
        raise HTTPException(status_code=404, detail="Job not found")

    # Check ownership
    if job.user_id != current_user.id:
        logger.warning(f"[JOB STATUS] User {current_user.id} unauthorized to access job {job_id}")
        raise HTTPException(status_code=403, detail="Not authorized to access this job")

    return {
        "job_id": job.id,
        "status": job.status,
        "result": job.result,
        "error": job.error
    }


# --- MCQ EVALUATION ---
class MCQAnswerSubmission(BaseModel):
    answers: Any


@router.post("/{job_id}/evaluate")
def evaluate_mcq_answers(
    job_id: str,
    request: MCQAnswerSubmission,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    logger.info(f"[MCQ EVALUATE] Evaluating answers for job {job_id} by user {current_user.username}")
    job = get_job(job_id, db=db)
    if not job:
        logger.warning(f"[MCQ EVALUATE] Job {job_id} not found in database.")
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != current_user.id:
        logger.warning(f"[MCQ EVALUATE] User {current_user.id} unauthorized to access job {job_id}")
        raise HTTPException(status_code=403, detail="Not authorized to access this job")

    if job.model != "mcq-gen":
        raise HTTPException(status_code=400, detail="Only mcq-gen jobs can be evaluated")

    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job is not completed yet (current status: {job.status})")

    if not isinstance(job.result, list):
        raise HTTPException(status_code=500, detail="MCQ job result is not in the correct format")

    parsed_answers = {}
    raw_answers = request.answers

    if isinstance(raw_answers, list):
        for idx, item in enumerate(raw_answers):
            if isinstance(item, str):
                parsed_answers[idx] = item
            elif isinstance(item, dict):
                q_idx = item.get("question_index")
                sel_opt = item.get("selected_option")
                if q_idx is not None and sel_opt is not None:
                    try:
                        parsed_answers[int(q_idx)] = str(sel_opt)
                    except (ValueError, TypeError):
                        raise HTTPException(status_code=422, detail=f"Invalid question_index: {q_idx}")
                else:
                    raise HTTPException(status_code=422, detail="Each item in answers list must contain 'question_index' and 'selected_option'")
            else:
                raise HTTPException(status_code=422, detail="Answers list must contain only strings or objects")
    elif isinstance(raw_answers, dict):
        for k, v in raw_answers.items():
            try:
                parsed_answers[int(k)] = str(v)
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail=f"Invalid dictionary key (must be integer index): {k}")
    else:
        raise HTTPException(status_code=422, detail="Answers must be a list or a dictionary")

    evaluation = []
    score = 0
    total_questions = len(job.result)

    for idx, mcq in enumerate(job.result):
        question_text = mcq.get("question", "")
        correct_answer = mcq.get("answer", "")
        
        selected_option = parsed_answers.get(idx)
        if selected_option is not None:
            is_correct = (str(selected_option).strip() == str(correct_answer).strip())
        else:
            is_correct = False
            
        if is_correct:
            score += 1
            
        evaluation.append({
            "question_index": idx,
            "question": question_text,
            "selected_option": selected_option,
            "correct_answer": correct_answer,
            "is_correct": is_correct
        })

    return {
        "job_id": job.id,
        "score": score,
        "total_questions": total_questions,
        "evaluation": evaluation
    }
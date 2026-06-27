import logging
import time
from database.jobs import get_job, update_job
from services.registry import get_model, LIVE_TEXT_SPACES
from utils.hf_parser import parse_model_output
from utils.metrics import log_metric, is_space_sleeping

logger = logging.getLogger("worker")

def run_job(job_id: str, enqueue_time: float = None):
    logger.info(f"[WORKER] Starting job {job_id}")
    job = get_job(job_id)
    if not job:
        logger.error(f"[WORKER] Job {job_id} not found in database.")
        return

    update_job(job_id, status="running")

    # Calculate queue wait time
    queue_wait_time = 0.0
    if enqueue_time is not None:
        queue_wait_time = time.time() - enqueue_time

    # Check if HF space is sleeping before we load or run it
    space_id = LIVE_TEXT_SPACES.get(job.model, {}).get("space")
    was_sleeping = False
    if space_id:
        was_sleeping = is_space_sleeping(space_id)

    start_time = time.time()
    wake_up_delay = 0.0

    try:
        # 1. Retrieve the adapter
        adapter = get_model(job.model)
        if not adapter:
            raise ValueError(f"Model adapter for '{job.model}' not found in registry.")

        # 2. Run the adapter prediction
        logger.info(f"[WORKER] Running adapter for job {job_id} (model: {job.model})")
        raw_result = adapter.run(job.input)

        latency = time.time() - start_time
        if was_sleeping:
            wake_up_delay = latency

        # Log metrics for success
        log_metric(
            model_name=job.model,
            latency=latency,
            success=True,
            queue_wait_time=queue_wait_time,
            wake_up_delay=wake_up_delay
        )

        # 3. Clean/parse the result
        logger.info(f"[WORKER] Parsing output for job {job_id}")
        cleaned_result = parse_model_output(job.model, raw_result)

        # 4. Handle parsing errors
        if isinstance(cleaned_result, dict) and "error" in cleaned_result:
            error_msg = cleaned_result["error"]
            logger.error(f"[WORKER] Parsing failed for job {job_id}: {error_msg}")
            update_job(job_id, status="error", error=error_msg)
            return

        # 5. Success
        logger.info(f"[WORKER] Job {job_id} completed successfully.")
        update_job(job_id, status="done", result=cleaned_result)

    except Exception as e:
        latency = time.time() - start_time
        if was_sleeping:
            wake_up_delay = latency

        # Log metrics for failure
        log_metric(
            model_name=job.model,
            latency=latency,
            success=False,
            queue_wait_time=queue_wait_time,
            wake_up_delay=wake_up_delay
        )

        logger.exception(f"[WORKER] Job {job_id} failed with exception.")
        update_job(job_id, status="error", error=str(e))
        raise


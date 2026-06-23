import logging
from database.jobs import get_job, update_job
from services.registry import get_model
from utils.hf_parser import parse_model_output

logger = logging.getLogger("worker")

def run_job(job_id: str):
    logger.info(f"[WORKER] Starting job {job_id}")
    job = get_job(job_id)
    if not job:
        logger.error(f"[WORKER] Job {job_id} not found in database.")
        return

    update_job(job_id, status="running")

    try:
        # 1. Retrieve the adapter
        adapter = get_model(job.model)
        if not adapter:
            raise ValueError(f"Model adapter for '{job.model}' not found in registry.")

        # 2. Run the adapter prediction
        logger.info(f"[WORKER] Running adapter for job {job_id} (model: {job.model})")
        raw_result = adapter.run(job.input)

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
        logger.exception(f"[WORKER] Job {job_id} failed with exception.")
        update_job(job_id, status="error", error=str(e))
        raise

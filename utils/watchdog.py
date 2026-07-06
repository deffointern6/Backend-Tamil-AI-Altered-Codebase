import datetime
import logging
import time
from database.db import SessionLocal
from database.models_db import Job
from redis import Redis
from rq import Queue, Retry
from settings.config import settings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("watchdog")

def cleanup_stuck_jobs(timeout_minutes: int = 15) -> int:
    """
    Scans the database for jobs stuck in 'running' status for longer than
    the timeout threshold, and marks them as failed.
    Returns the number of jobs cleaned up.
    """
    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        threshold = now - datetime.timedelta(minutes=timeout_minutes)
        
        # Query running jobs that haven't been updated since the threshold
        stuck_jobs = db.query(Job).filter(
            Job.status == "running",
            Job.updated_at < threshold
        ).all()
        
        if not stuck_jobs:
            logger.info("Watchdog: No stuck running jobs found.")
            return 0
            
        logger.warning(f"Watchdog: Found {len(stuck_jobs)} stuck jobs. Marking them as failed.")
        
        for job in stuck_jobs:
            job.status = "error"
            job.error = f"Job execution timed out. Active worker terminated abnormally or exceeded {timeout_minutes} minute limit."
            logger.info(f"Watchdog: Cleaned up stuck job {job.id} (model: {job.model}, user: {job.user_id})")
            
        db.commit()
        return len(stuck_jobs)
    except Exception as e:
        logger.exception(f"Watchdog: Error occurred during job cleanup: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def recover_lost_queued_jobs(timeout_minutes: int = 10) -> int:
    """
    Scans the database for jobs stuck in 'queued' status for longer than the
    timeout threshold (e.g. lost due to a Redis crash) and re-enqueues them.
    """
    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        threshold = now - datetime.timedelta(minutes=timeout_minutes)
        
        # Query queued jobs that were created before the threshold
        stuck_queued = db.query(Job).filter(
            Job.status == "queued",
            Job.created_at < threshold
        ).all()
        
        if not stuck_queued:
            logger.info("Watchdog: No orphaned queued jobs found.")
            return 0
            
        logger.warning(f"Watchdog: Found {len(stuck_queued)} stuck queued jobs. Re-enqueuing them into Redis.")
        
        # Initialize Redis connection for enqueuing
        redis_url = settings.redis_url if settings.redis_url else "redis://localhost:6379/0"
        redis_conn = Redis.from_url(redis_url)
        high_queue = Queue("high", connection=redis_conn)
        default_queue = Queue("default", connection=redis_conn)
        
        count = 0
        for job in stuck_queued:
            target_queue = high_queue if job.model in ["proofreader", "tongue-twister"] else default_queue
            
            # Re-enqueue with the standard auto-retry configuration
            target_queue.enqueue(
                "worker.run_job", 
                job.id, 
                time.time(), 
                job_timeout=600,
                retry=Retry(max=3, interval=[2, 5, 10])
            )
            logger.info(f"Watchdog: Re-enqueued job {job.id} into '{target_queue.name}' queue.")
            count += 1
            
        return count
    except Exception as e:
        logger.exception(f"Watchdog: Error occurred during queued jobs recovery: {e}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    print("Watchdog: Starting cleanup and recovery routines...")
    cleaned = cleanup_stuck_jobs()
    recovered = recover_lost_queued_jobs()
    print(f"Watchdog: Completed. Cleaned up: {cleaned} stuck running jobs. Recovered: {recovered} lost queued jobs.")

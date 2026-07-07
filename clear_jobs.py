import os
import sys
from redis import Redis
from rq import Queue
from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry

# Add current directory to path so we can import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.db import SessionLocal
from database.models_db import Job
from settings.config import settings

def clear_all_jobs():
    print("Connecting to Database and Redis...")
    
    # 1. Clear database jobs table
    db = SessionLocal()
    try:
        num_deleted = db.query(Job).delete()
        db.commit()
        print(f" -> Deleted {num_deleted} job records from the database.")
    except Exception as e:
        db.rollback()
        print(f" -> Error clearing database: {e}")
    finally:
        db.close()

    # 2. Clear Redis RQ queues and registries
    try:
        redis_conn = Redis.from_url(settings.redis_url)
        
        # Empty high and default queues
        for queue_name in ["high", "default"]:
            q = Queue(queue_name, connection=redis_conn)
            q.empty()
            
            # Clean registries (Failed, Finished, Started)
            FailedJobRegistry(queue_name, connection=redis_conn).cleanup()
            FinishedJobRegistry(queue_name, connection=redis_conn).cleanup()
            StartedJobRegistry(queue_name, connection=redis_conn).cleanup()
            
            # Delete any remaining keys associated with these registries/queues
            # (which includes scheduled or deferred jobs)
            for key in redis_conn.scan_iter(f"rq:job:*"):
                redis_conn.delete(key)
                
        # 3. Clear metrics logs
        redis_conn.delete("metrics:raw_log")
        
        print(" -> Cleared all queues, registries, jobs, and metrics from Redis.")
        print("Done! Everything is fresh.")
    except Exception as e:
        print(f" -> Error clearing Redis: {e}")

if __name__ == "__main__":
    clear_all_jobs()

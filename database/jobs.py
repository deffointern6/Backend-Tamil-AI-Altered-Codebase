from sqlalchemy.orm import Session
from database.db import SessionLocal
from database.models_db import Job
from contextlib import contextmanager

@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def create_job(user_id: str, model: str, input_data, db: Session = None) -> str:
    if db is not None:
        job = Job(user_id=user_id, model=model, input=input_data)
        db.add(job)
        db.commit()
        return job.id

    with db_session() as session:
        job = Job(user_id=user_id, model=model, input=input_data)
        session.add(job)
        session.commit()
        return job.id

def get_job(job_id: str, db: Session = None) -> Job | None:
    if db is not None:
        return db.query(Job).filter(Job.id == job_id).first()

    with db_session() as session:
        job = session.query(Job).filter(Job.id == job_id).first()
        if job:
            session.refresh(job)
        return job

def update_job(job_id: str, db: Session = None, **fields) -> None:
    if db is not None:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
            db.commit()
        return

    with db_session() as session:
        job = session.query(Job).filter(Job.id == job_id).first()
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
            session.commit()


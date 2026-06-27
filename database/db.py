from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from settings.config import settings

db_url = str(settings.database_url)

# Replace legacy 'postgres://' with 'postgresql://'
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Default postgresql:// to use postgresql+psycopg:// to support psycopg v3
if db_url.startswith("postgresql://") and "+psycopg" not in db_url:
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

# SQLite checks - only for local development and unit testing
connect_args = {}
if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()

# Create tables automatically on startup/import
# We import models_db here (after Base is defined) to avoid circular imports.
import database.models_db
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


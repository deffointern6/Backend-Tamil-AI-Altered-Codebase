from sqlalchemy import create_engine, inspect, text
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
    if settings.environment.lower() == "production":
        raise RuntimeError("SQLite is not supported in a production environment. Configure a PostgreSQL database.")
    connect_args["check_same_thread"] = False

engine_kwargs = {
    "pool_pre_ping": True
}
if not db_url.startswith("sqlite"):
    engine_kwargs["pool_size"] = settings.db_pool_size
    engine_kwargs["max_overflow"] = settings.db_max_overflow
    engine_kwargs["pool_recycle"] = 1800
    engine_kwargs["pool_timeout"] = 30

engine = create_engine(
    db_url,
    connect_args=connect_args,
    **engine_kwargs
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()

import database.models_db
Base.metadata.create_all(bind=engine)

def upgrade_db_schema():
    """
    Dynamically upgrades the database schema if tables already exist but are missing columns.
    This ensures local sqlite/postgres environments upgrade automatically without needing manual migration files.
    """
    inspector = inspect(engine)
    if "accounts" in inspector.get_table_names():
        existing_cols = [c["name"] for c in inspector.get_columns("accounts")]
        with engine.connect() as conn:
            # Check and add username
            if "username" not in existing_cols:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN username VARCHAR"))
            # Check and add email
            if "email" not in existing_cols:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN email VARCHAR"))
            # Check and add dob
            if "dob" not in existing_cols:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN dob VARCHAR"))
            conn.commit()

    if "users" in inspector.get_table_names():
        existing_cols = [c["name"] for c in inspector.get_columns("users")]
        with engine.connect() as conn:
            # Check and add is_admin
            if "is_admin" not in existing_cols:
                # Add is_admin column as BOOLEAN with a default value of False
                # Handles sqlite/postgres compatibility
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
            conn.commit()

# Run the upgrade schema routine
upgrade_db_schema()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


"""
Real Postgres connection via SQLAlchemy. Replaces the raw sqlite3 usage in the
MVP's audit.py — that file is superseded by app/models.py + app/db.py from here on.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a session, always closes it, even on error."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

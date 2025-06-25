"""
Database Module
SQLAlchemy configuration and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

engine = None
SessionLocal = None

def get_engine(database_url: str):
    """Get or create database engine"""
    global engine
    if engine is None:
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False
        )
    return engine

def get_session_factory(db_engine):
    """Get session factory"""
    return sessionmaker(bind=db_engine)

def init_database(database_url: str):
    """Initialize database with tables"""
    global engine, SessionLocal
    
    engine = get_engine(database_url)
    SessionLocal = get_session_factory(engine)
    
    from .models import Base
    Base.metadata.create_all(engine)
    
    logger.info("Database initialized successfully")

@contextmanager
def db_session():
    """Database session context manager"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

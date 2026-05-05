from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from .config import settings

engine = create_engine(
    settings.AGENT_BRIDGE_SQLITE_PATH, 
    connect_args={"check_same_thread": False} if "sqlite" in settings.AGENT_BRIDGE_SQLITE_PATH else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class StoredAnalysis(Base):
    __tablename__ = "stored_analyses"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String, unique=True, index=True, nullable=False)
    headline = Column(String, nullable=True)
    risk_signals = Column(JSON, nullable=True)
    priority = Column(String, nullable=True)
    raw_llm_output = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

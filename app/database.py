from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import json

Base = declarative_base()

class InteractionLog(Base):
    __tablename__ = 'interactions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # 原始请求
    raw_request = Column(JSON) # 存整个 Request JSON
    
    # 剪枝后
    pruned_tools = Column(JSON) # 存剪枝后的 Tools 列表
    
    # 真正发给大模型的消息体 (NEW)
    final_payload = Column(JSON) 
    
    # 模型响应
    raw_response = Column(JSON) # 存 LLM 返回的 JSON
    
    # 状态/耗时等（可选）
    model_used = Column(String)
    latency_ms = Column(Integer)
    status = Column(String) # "success", "error"
    pruned_tool_count = Column(Integer, nullable=True) # NEW: Number of tools after pruning

class Config(Base):
    __tablename__ = 'config'
    key = Column(String, primary_key=True)
    value = Column(String) # JSON encoded value or plain string

class User(Base):
    __tablename__ = 'users'
    username = Column(String, primary_key=True)
    hashed_password = Column(String)

class CustomModel(Base):
    __tablename__ = 'custom_models'
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String) # e.g., 'gemini', 'openai'
    name = Column(String)     # Label displayed in UI
    value = Column(String)    # Internal value used for API calls

# SQLite DB
DATABASE_URL = "sqlite:///./sen_gateway.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

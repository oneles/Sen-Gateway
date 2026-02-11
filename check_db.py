from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import InteractionLog, Base

DATABASE_URL = "sqlite:///./sen_gateway.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

try:
    count = db.query(InteractionLog).count()
    print(f"Total Logs in DB: {count}")
    
    if count > 0:
        latest = db.query(InteractionLog).order_by(InteractionLog.timestamp.desc()).first()
        print(f"Latest Log ID: {latest.id}")
        print(f"Latest Timestamp: {latest.timestamp}")
        print(f"Status: {latest.status}")
except Exception as e:
    print(f"Error querying DB: {e}")
finally:
    db.close()

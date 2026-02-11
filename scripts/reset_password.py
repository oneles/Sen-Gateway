from database import SessionLocal, User, init_db
import security
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_admin():
    # Ensure tables exist
    init_db()
    
    db = SessionLocal()
    try:
        username = "admin"
        password = "88888888"
        
        # Calculate new hash
        hashed_pw = security.get_password_hash(password)
        
        user = db.query(User).filter(User.username == username).first()
        
        if user:
            logger.info(f"User '{username}' found. Updating password...")
            user.hashed_password = hashed_pw
        else:
            logger.info(f"User '{username}' not found. Creating new user...")
            user = User(username=username, hashed_password=hashed_pw)
            db.add(user)
            
        db.commit()
        logger.info(f"✅ Admin password reset successfully to: {password}")
        
        # Verify
        verify_user = db.query(User).filter(User.username == username).first()
        if verify_user and security.verify_password(password, verify_user.hashed_password):
             logger.info("✅ Verification: Password hash matches.")
        else:
             logger.error("❌ Verification: Password hash mismatch!")

    except Exception as e:
        logger.error(f"Error resetting admin: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reset_admin()

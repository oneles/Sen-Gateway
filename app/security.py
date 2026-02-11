from cryptography.fernet import Fernet
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
import os

# --- Config ---
SECRET_FILE = "secret.key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# --- API Key Encryption ---
def load_key():
    if not os.path.exists(SECRET_FILE):
        key = Fernet.generate_key()
        with open(SECRET_FILE, "wb") as key_file:
            key_file.write(key)
    return open(SECRET_FILE, "rb").read()

cipher_suite = Fernet(load_key())

def encrypt_value(text: str) -> str:
    if not text: return ""
    return cipher_suite.encrypt(text.encode()).decode()

def decrypt_value(text: str) -> str:
    if not text: return ""
    try:
        return cipher_suite.decrypt(text.encode()).decode()
    except Exception:
        return "" # Fail safe

# --- Auth ---
# Use pbkdf2_sha256 to avoid bcrypt version conflicts with passlib
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Use a fixed secret for JWT signature (in production this should be in .env)
# For simplicity, we reuse the Fernet key bytes as the JWT secret
JWT_SECRET_KEY = load_key().decode()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.JWTError:
        return None

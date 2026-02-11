import requests
import sys

# 1. Login
login_url = "http://localhost:8000/api/login"
data = {"username": "admin", "password": "88888888"}
print(f"Logging in to {login_url}...")

try:
    s = requests.Session()
    res = s.post(login_url, data=data)
    
    if res.status_code != 200:
        print(f"Login failed: {res.status_code} {res.text}")
        sys.exit(1)
        
    print("Login successful.")
    
    # 2. Get Logs
    logs_url = "http://localhost:8000/api/logs"
    print(f"Fetching logs from {logs_url}...")
    
    res = s.get(logs_url)
    
    if res.status_code != 200:
        print(f"Get logs failed: {res.status_code} {res.text}")
        sys.exit(1)
        
    logs = res.json()
    print(f"Received {len(logs)} logs.")
    if len(logs) > 0:
        print("First log sample:", logs[0])
    
except Exception as e:
    print(f"Error: {e}")

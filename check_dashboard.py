from dashboard import dashboard
from database import get_db, InteractionLog
from fastapi import Request
import asyncio

async def test():
    # Mock request and db
    class MockDB:
        def query(self, *args): return self
        def filter(self, *args): return self
        def order_by(self, *args): return self
        def limit(self, *args): return self
        def all(self): return [] # Return empty list to test rendering
        
    class MockRequest:
        cookies = {"access_token": "valid_token"}
        headers = {}
        
    try:
        # We can't easily mock the Depends injection, but we can look at the source code string directly?
        # No, dashboard function returns HTMLResponse.
        # Let's just read the file content and try to exec the f-string part manually?
        # Too complex.
        
        # Let's just read the file and print the JS part near loadLogList
        with open("/home/zhangwansen/.openclaw/workspace/Sen-Gateway/dashboard.py", "r") as f:
            content = f.read()
            
        start = content.find("async function loadLogList")
        end = content.find("async function selectLog")
        print(content[start:end])
        
    except Exception as e:
        print(e)

if __name__ == "__main__":
    asyncio.run(test())

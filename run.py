
import os
import sqlite3
try:
    _conn = sqlite3.connect("sen_gateway.db")
    _cur = _conn.cursor()
    _cur.execute("SELECT value FROM config WHERE key='proxy_enabled'")
    _proxy_enabled = _cur.fetchone()
    if _proxy_enabled and _proxy_enabled[0] == "true":
        _cur.execute("SELECT value FROM config WHERE key='proxy_url'")
        _proxy_url = _cur.fetchone()
        _url = _proxy_url[0] if _proxy_url else "http://127.0.0.1:7897"
        os.environ["http_proxy"] = _url
        os.environ["https_proxy"] = _url
        os.environ["HTTP_PROXY"] = _url
        os.environ["HTTPS_PROXY"] = _url
    _conn.close()
except Exception as e:
    pass

import os
import sys

# Clear specific proxy env vars BEFORE any other imports to prevent litellm/httpx from crashing on socks
for key in ["all_proxy", "ALL_PROXY"]:
    if key in os.environ:
        del os.environ[key]

# Add the current directory to sys.path so we can import from 'app'
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn
    # Use the import string format to support the app directory structure
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)

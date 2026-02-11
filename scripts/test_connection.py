import os
import time
import requests

# 1. 强制设置代理，模拟 Sen-Gateway 的行为
proxy_url = "http://127.0.0.1:7897"
os.environ["http_proxy"] = proxy_url
os.environ["https_proxy"] = proxy_url

print(f"Testing connection through proxy: {proxy_url}")
print("-" * 40)

# 2. 测试访问 Google (连通性)
target_url = "https://www.google.com"
print(f"Attempting to connect to {target_url}...")

try:
    start_time = time.time()
    response = requests.get(target_url, timeout=10) # 设置 10 秒超时，防止无限卡死
    end_time = time.time()
    
    print(f"✅ Connection Successful!")
    print(f"Status Code: {response.status_code}")
    print(f"Latency: {int((end_time - start_time) * 1000)}ms")
    print(f"Response size: {len(response.content)} bytes")

except requests.exceptions.ProxyError as e:
    print(f"❌ Proxy Error: Failed to connect to proxy.")
    print(f"Details: {e}")
except requests.exceptions.ConnectTimeout as e:
    print(f"❌ Connection Timeout: The proxy didn't respond in time.")
    print(f"Details: {e}")
except requests.exceptions.SSLError as e:
    print(f"❌ SSL Error: SSL handshake failed (check proxy SSL/TLS settings).")
    print(f"Details: {e}")
except Exception as e:
    print(f"❌ General Error: {type(e).__name__}")
    print(f"Details: {e}")

print("-" * 40)

# 3. 测试访问 Google Gemini API 端点 (可选，确认 API 可达)
api_url = "https://generativelanguage.googleapis.com"
print(f"Attempting to connect to Gemini API endpoint: {api_url}...")
try:
    response = requests.get(api_url, timeout=5)
    print(f"✅ API Endpoint Reachable (Status: {response.status_code})")
except Exception as e:
    print(f"⚠️ API Endpoint Warning: {e}")

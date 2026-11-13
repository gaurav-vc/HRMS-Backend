import urllib.request
import json
import time

# 1. Simulate Login as site admin
login_payload = json.dumps({"username": "gauravkokane05@gmail.com", "password": "DummyPassword123"}).encode('utf-8')
req1 = urllib.request.Request(
    "http://127.0.0.1:8000/api/auth/token/",
    data=login_payload,
    headers={"Content-Type": "application/json", "X-Client-Platform": "WEB"}
)
try:
    urllib.request.urlopen(req1)
except Exception:
    pass

time.sleep(0.5)

# 2. Simulate mobile app request from tenant org_2
req2 = urllib.request.Request(
    "http://127.0.0.1:8000/api/employees/",
    headers={
        "X-Client-Platform": "MOBILE",
        "User-Agent": "HRMS-Mobile/1.0.0 (Android 14)",
    }
)
try:
    urllib.request.urlopen(req2)
except Exception:
    pass

time.sleep(0.5)

# 3. Simulate punch attendance request
punch_payload = json.dumps({"action": "check_in"}).encode('utf-8')
req3 = urllib.request.Request(
    "http://127.0.0.1:8000/api/attendance/punch/",
    data=punch_payload,
    headers={
        "Content-Type": "application/json",
        "X-Client-Platform": "WEB",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    }
)
try:
    urllib.request.urlopen(req3)
except Exception:
    pass

print("Actions simulated successfully!")


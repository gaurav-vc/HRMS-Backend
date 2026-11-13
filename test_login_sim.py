import urllib.request
import json

payload = json.dumps({"username": "Admin", "password": "AdminPassword123"}).encode('utf-8')
# Note: We can also test with Admin123@gmail.com
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/auth/token/",
    data=payload,
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req) as resp:
        print("Login response status:", resp.status)
        data = json.loads(resp.read().decode('utf-8'))
        print("Tokens received:", "access" in data)
except urllib.error.HTTPError as e:
    print("Login HTTP error:", e.code, e.read().decode('utf-8'))
except Exception as e:
    print("Login general error:", e)


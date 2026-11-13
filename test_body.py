import json

body_raw = b'{"username": "Admin", "password": "AdminPassword123"}'
actor_email = ""
try:
    p_data = json.loads(body_raw.decode("utf-8", errors="ignore"))
    if isinstance(p_data, dict):
        actor_email = p_data.get("email") or p_data.get("username") or ""
except Exception as e:
    print("Error:", e)
print("Extracted actor_email:", actor_email)


import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
import urllib.request
import json

User = get_user_model()
admin = User.objects.filter(is_superuser=True).first()
token = str(RefreshToken.for_user(admin).access_token)

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/superadmin/telemetry/overview/",
    headers={"Authorization": f"Bearer {token}"}
)

with urllib.request.urlopen(req) as resp:
    raw = resp.read()
    print("Response size in bytes:", len(raw))
    data = json.loads(raw.decode('utf-8'))
    print("Active anomalies:", len(data.get("data", {}).get("activeAnomalies", [])))
    print("Recent traces:", len(data.get("data", {}).get("recentTraces", [])))
    print("Endpoints count in overview:", len(data.get("data", {}).get("endpoints", [])))


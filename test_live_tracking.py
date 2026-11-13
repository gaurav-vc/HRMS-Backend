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
    "http://127.0.0.1:8000/api/v1/superadmin/telemetry/logs/?hide_heartbeats=true&page=1&pageSize=10",
    headers={"Authorization": f"Bearer {token}"}
)

with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    traces = data.get("data", {}).get("traces", [])
    print(f"Top {len(traces)} live traces in running server:")
    for i, t in enumerate(traces):
        print(f"[{i+1}] {t.get('timestamp')} | {t.get('method')} {t.get('endpoint')} | Status: {t.get('statusCode')} | Platform: {t.get('platform')} | Actor: {t.get('actorEmail')} | Tenant: {t.get('tenantId')}")

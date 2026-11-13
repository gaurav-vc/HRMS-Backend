import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from core.telemetry import _LIVE_REQUEST_TRACES

print(f"Total traces recorded: {len(_LIVE_REQUEST_TRACES)}")
for i, t in enumerate(list(_LIVE_REQUEST_TRACES)[:5]):
    print(f"[{i+1}] {t.get('method')} {t.get('endpoint')} | Status: {t.get('statusCode')} | Actor: {t.get('actorEmail')} | Tenant: {t.get('tenantId')} | Heartbeat: {t.get('isHeartbeat')}")


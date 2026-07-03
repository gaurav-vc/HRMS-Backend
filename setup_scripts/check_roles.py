import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from organisation.models import Role

roles = Role.objects.all()
for r in roles:
    print(f"Role: {r.name}")
    print(f"  permissions: {r.permissions}")
    print(f"  dashboard_type column: {r.dashboard_type}")

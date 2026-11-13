import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
for u in User.objects.all()[:15]:
    emp = getattr(u, 'employee_profile', None)
    org_id = getattr(emp, 'organization_id', None) if emp else None
    role = getattr(emp, 'role', None) if emp else None
    print(f"User: id={u.id}, email={u.email}, username={u.username}, is_superuser={u.is_superuser}, role={role}, org_id={org_id}")

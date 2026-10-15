import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from authentication.permissions import _get_admin_sites, isolate_queryset
from django.contrib.auth.models import User
from employees.models import Employee
from organisation.models import Site, Department, Designation, Role, Entity, Branch
print("=== ALL SITES ===")
for s in Site.objects.all():
    print(f"Site #{s.id}: name='{s.name}', is_sub_site={s.is_sub_site}, contact='{s.contact_email}', org_id={s.organization_id}, branch_id={s.branch_id}")

print("\n=== ALL ROLES IN DB ===")
for r in Role.objects.all().order_by('id'):
    print(f"Role #{r.id}: name='{r.name}', code='{r.code}', site_id={r.site_id}, org_id={r.organization_id}")

print("\n=== ISOLATION TEST FOR ALL MAIN SITES ===")
for s in Site.objects.filter(is_sub_site=False):
    admin_user = User.objects.filter(email=s.contact_email).first()
    if not admin_user:
        continue
    print(f"\n--- Testing for Site Admin of '{s.name}' (#{s.id}, {admin_user.email}) ---")
    emp = getattr(admin_user, 'employee_profile', None)
    print(f"Employee site: {getattr(emp, 'site', None)}, role: {getattr(emp, 'role', None)}")
    print(f"Admin Sites: list={list(_get_admin_sites(admin_user).values_list('name', flat=True))}")
    
    visible_sites = list(isolate_queryset(Site.objects.all(), admin_user).values_list('name', flat=True))
    visible_roles = list(isolate_queryset(Role.objects.all(), admin_user).values_list('name', flat=True))
    visible_emps = isolate_queryset(Employee.objects.all(), admin_user).count()
    
    print(f"Visible Sites ({len(visible_sites)}): {visible_sites}")
    print(f"Visible Roles ({len(visible_roles)}): {visible_roles}")
    print(f"Visible Employees count: {visible_emps}")

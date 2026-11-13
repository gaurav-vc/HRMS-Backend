import os
import sys
sys.path.insert(0, 'C:/Hrms/HRMS-Backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from authentication.models import User
from employees.models import Employee
from organisation.models import Entity, Branch, Site, Role
from admin_org.models import Organization
from authentication.permissions import _get_tenant_scope, isolate_queryset

def run_tests():
    print("==================================================")
    print("RUNNING PHASE 2 MULTI-TENANT ISOLATION TESTS")
    print("==================================================")

    # 1. Setup Tenant 2 ("Tenant B / Apex Corp")
    print("\n--- Test 1: Setup isolated Tenant B fixtures ---")
    org_b, _ = Organization.objects.get_or_create(name="Apex Global Ltd")
    ent_b, _ = Entity.objects.get_or_create(name="Apex Technologies", organization=org_b, defaults={"code": "APEX-TECH"})
    branch_b, _ = Branch.objects.get_or_create(name="Apex North Branch", entity=ent_b, defaults={"code": "APEX-NB"})
    site_b, _ = Site.objects.get_or_create(
        name="Apex Tower Site",
        organization=org_b,
        branch=branch_b,
        defaults={"is_sub_site": False, "contact_email": "apexadmin@apex.com"}
    )
    
    user_b, _ = User.objects.get_or_create(username="apex_admin", defaults={"email": "apexadmin@apex.com"})
    user_b.set_password("123")
    user_b.is_superuser = False
    user_b.is_staff = False
    user_b.save()

    emp_b, _ = Employee.objects.get_or_create(
        code="EMP-APEX-001",
        defaults={
            "user": user_b,
            "first_name": "Apex",
            "last_name": "Admin",
            "email": "apexadmin@apex.com",
            "organization": org_b,
            "entity": ent_b,
            "branch": branch_b,
            "site": site_b,
            "role": "site_admin"
        }
    )
    emp_b.organization = org_b
    emp_b.entity = ent_b
    emp_b.branch = branch_b
    emp_b.site = site_b
    emp_b.role = "site_admin"
    emp_b.save()

    print(f"Tenant B created: Org={org_b.id}, Entity={ent_b.id}, Branch={branch_b.id}, Site={site_b.id}, User={user_b.username}")

    # 2. Test Tenant A (Lotus siteadmin) vs Tenant B (Apex admin)
    print("\n--- Test 2: Verify Cross-Tenant Leakage Prevention ---")
    user_lotus = User.objects.get(username="siteadmin")
    
    # Query all employees for Lotus admin
    lotus_employees = isolate_queryset(Employee.objects.all(), user_lotus)
    lotus_emp_ids = set(lotus_employees.values_list('id', flat=True))
    assert emp_b.id not in lotus_emp_ids, "CRITICAL ERROR: Lotus admin can see Apex employee!"
    print(f"PASS: Lotus admin cannot see Apex employee (Total visible: {len(lotus_emp_ids)})")

    # Query all entities for Lotus admin
    lotus_entities = isolate_queryset(Entity.objects.all(), user_lotus)
    lotus_ent_ids = set(lotus_entities.values_list('id', flat=True))
    assert ent_b.id not in lotus_ent_ids, "CRITICAL ERROR: Lotus admin can see Apex entity!"
    print(f"PASS: Lotus admin cannot see Apex entity (Total visible: {len(lotus_ent_ids)})")

    # Query all sites for Lotus admin
    lotus_sites = isolate_queryset(Site.objects.all(), user_lotus)
    lotus_site_ids = set(lotus_sites.values_list('id', flat=True))
    assert site_b.id not in lotus_site_ids, "CRITICAL ERROR: Lotus admin can see Apex site!"
    print(f"PASS: Lotus admin cannot see Apex site (Total visible: {len(lotus_site_ids)})")

    # Now verify inverse: Apex admin querying
    apex_employees = isolate_queryset(Employee.objects.all(), user_b)
    apex_emp_ids = set(apex_employees.values_list('id', flat=True))
    assert user_lotus.employee_profile.id not in apex_emp_ids, "CRITICAL ERROR: Apex admin can see Lotus employees!"
    print(f"PASS: Apex admin cannot see Lotus employee (Total visible: {len(apex_emp_ids)})")

    # 3. Test Fallback when employee.site is None
    print("\n--- Test 3: Fallback resolution when employee.site is None ---")
    user_no_site, _ = User.objects.get_or_create(username="apex_user_no_site", defaults={"email": "nosite@apex.com"})
    user_no_site.set_password("123")
    user_no_site.save()

    emp_no_site, _ = Employee.objects.get_or_create(
        code="EMP-APEX-002",
        defaults={
            "user": user_no_site,
            "first_name": "NoSite",
            "last_name": "Worker",
            "email": "nosite@apex.com",
            "organization": org_b,
            "entity": ent_b,
            "branch": branch_b,
            "site": None, # EXPLICITLY NULL
            "role": "org_admin" # Has Corporate scope!
        }
    )
    emp_no_site.site = None
    emp_no_site.organization = org_b
    emp_no_site.entity = ent_b
    emp_no_site.branch = branch_b
    emp_no_site.role = "org_admin"
    emp_no_site.save()

    # Scope resolution check
    all_sites, branches, entities, t_site = _get_tenant_scope(user_no_site)
    print(f"Scope for user with null site: Sites={all_sites}, Branches={branches}, Entities={entities}, TenantSite={t_site}")
    assert ent_b.id in entities, "FAIL: Entity was not resolved for employee with null site!"
    assert branch_b.id in branches, "FAIL: Branch was not resolved for employee with null site!"
    assert site_b.id in all_sites, "FAIL: Site was not resolved for employee with null site!"
    print("PASS: _get_tenant_scope successfully resolved tenant boundary from entity/branch without site FK!")

    # Query check for employee with null site
    visible_employees = isolate_queryset(Employee.objects.all(), user_no_site)
    assert visible_employees.count() >= 2, f"FAIL: Expected at least 2 employees, got {visible_employees.count()}"
    assert emp_b in visible_employees, "FAIL: Could not see colleagues in same entity!"
    assert user_lotus.employee_profile not in visible_employees, "CRITICAL ERROR: Leaked Lotus employees!"
    print(f"PASS: Employee with null site sees all {visible_employees.count()} colleagues in Apex and 0 from Lotus!")

    # 4. Test IDOR Write Prevention
    print("\n--- Test 4: Verify Cross-Tenant IDOR Write Prevention ---")
    from rest_framework.test import APIRequestFactory, force_authenticate
    from rest_framework.exceptions import PermissionDenied
    from announcements.views import AnnouncementViewSet

    factory = APIRequestFactory()
    # Lotus admin attempts to create an announcement assigned to Apex entity (IDOR attempt)
    request = factory.post('/api/announcements/', {'title': 'Malicious Post', 'content': 'IDOR test', 'entity': ent_b.id}, format='json')
    force_authenticate(request, user=user_lotus)

    view = AnnouncementViewSet.as_view({'post': 'create'})
    try:
        response = view(request)
        if response.status_code == 403:
            print("PASS: API blocked cross-tenant assignment with HTTP 403 Forbidden!")
        else:
            raise AssertionError(f"FAIL: Cross-tenant creation returned status {response.status_code}!")
    except PermissionDenied:
        print("PASS: PermissionDenied exception properly triggered for cross-tenant IDOR write!")

    print("\n==================================================")
    print("ALL PHASE 2 MULTI-TENANT ISOLATION TESTS PASSED!")
    print("==================================================")

if __name__ == '__main__':
    run_tests()

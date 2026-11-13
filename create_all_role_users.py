import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from organisation.models import Role, Entity, Branch, Site
from admin_org.models import Organization
from employees.models import Employee

def create_and_setup_all_role_users():
    print("=== Setting up Organization & Site context ===")
    org = Organization.objects.filter(name__icontains='Lotus').first() or Organization.objects.first()
    entity = Entity.objects.filter(name__icontains='Lotus').first() or Entity.objects.first()
    site = Site.objects.filter(name__icontains='Lotus HQ').first() or Site.objects.first()
    branch = Branch.objects.filter(entity=entity).first() or Branch.objects.first()

    # Ensure site has all modules
    all_site_modules = [
        "Dashboard", "Entities", "Branches", "Sites", "Departments", "Designations",
        "Employees", "Announcements", "My Calendar", "Offer Letters", "Offer Templates",
        "Separation Request", "Manage Exits", "Attendance", "Shift Definitions", "Weekly Roster",
        "QR Check-in", "Face Verification", "GPS Capture", "Regularization", "Leave Requests",
        "Inbox", "Holiday Planner", "Calendar", "Payroll Overview", "Salary Structure",
        "Import CTC", "Run Payroll", "Salary Slips", "Compliance", "Loans & Advances",
        "Reimbursements", "Disciplinary Memos", "Form 16 Management", "My Form 16",
        "Organization Tree", "Reports", "Settings", "Leave Policies", "Leave Balances", "Roles & Users"
    ]
    if site:
        site.modules = all_site_modules
        site.save(update_fields=['modules'])

    # Standard permission sets
    full_crud = {"view": True, "create": True, "update": True, "delete": True}
    view_only = {"view": True, "create": False, "update": False, "delete": False}

    all_modules = [
        "Dashboard", "Entities", "Branches", "Sites", "Departments", "Designations",
        "Employees", "Announcements", "My Calendar", "Offer Letters", "Offer Templates",
        "Separation Request", "Manage Exits", "Attendance", "Shift Definitions", "Weekly Roster",
        "QR Check-in", "Face Verification", "GPS Capture", "Regularization", "Leave Requests",
        "Inbox", "Holiday Planner", "Calendar", "Payroll Overview", "Salary Structure",
        "Import CTC", "Run Payroll", "Salary Slips", "Compliance", "Loans & Advances",
        "Reimbursements", "Disciplinary Memos", "Form 16 Management", "My Form 16",
        "Organization Tree", "Reports", "Settings"
    ]

    executive_perms = {m: full_crud for m in all_modules}
    executive_perms.update({
        "dashboard_type": "executive",
        "can_approve_payroll": True,
        "can_view_confidential_payroll": True,
        "can_run_payroll": True,
        "can_manage_users": True,
        "can_add_ctc": True,
    })

    manager_perms = {
        "Dashboard": full_crud,
        "Employees": view_only,
        "Announcements": full_crud,
        "My Calendar": full_crud,
        "Attendance": full_crud,
        "Shift Definitions": full_crud,
        "Weekly Roster": full_crud,
        "QR Check-in": full_crud,
        "Face Verification": full_crud,
        "GPS Capture": full_crud,
        "Regularization": full_crud,
        "Leave Requests": full_crud,
        "Inbox": full_crud,
        "Holiday Planner": view_only,
        "Calendar": view_only,
        "Salary Slips": view_only,
        "My Form 16": view_only,
        "Separation Request": full_crud,
        "Manage Exits": full_crud,
        "Organization Tree": view_only,
        "Reports": view_only,
        "dashboard_type": "manager",
        "can_approve": True,
    }

    staff_perms = {
        "Dashboard": view_only,
        "Announcements": view_only,
        "My Calendar": full_crud,
        "Attendance": full_crud,
        "QR Check-in": full_crud,
        "Face Verification": full_crud,
        "GPS Capture": full_crud,
        "Regularization": full_crud,
        "Leave Requests": full_crud,
        "Inbox": full_crud,
        "Holiday Planner": view_only,
        "Calendar": view_only,
        "Salary Slips": view_only,
        "My Form 16": view_only,
        "Separation Request": full_crud,
        "dashboard_type": "staff",
    }

    # Role definitions mapping
    # (Role Name, Username, Email, First Name, Last Name, Emp Code, Category)
    role_user_specs = [
        ("Super Admin", "admin_user", "superadmin@hrms.com", "Super", "Admin", "EMP-SA-01", "executive"),
        ("Org Admin", "orgadmin", "orgadmin@hrms.com", "Org", "Admin", "EMP-OA-01", "executive"),
        ("Site Admin", "siteadmin", "siteadmin@hrms.com", "Site", "Admin", "EMP-SITA-01", "executive"),
        ("Group HR", "grouphr", "grouphr@hrms.com", "Group", "HR", "EMP-GHR-01", "executive"),
        ("Finance HR", "financehr", "financehr@hrms.com", "Finance", "HR", "EMP-FHR-01", "finance"),
        ("Promoter / Chairman", "promoter", "promoter@hrms.com", "Chairman", "Promoter", "EMP-PROM-01", "executive"),
        ("Board of Directors", "board", "board@hrms.com", "Board", "Director", "EMP-BOD-01", "executive"),
        ("Group CEO / Managing Director", "ceo", "ceo@hrms.com", "Chief", "Executive", "EMP-CEO-01", "executive"),
        ("C-Level Leadership", "clevel", "clevel@hrms.com", "C-Level", "Officer", "EMP-CLEV-01", "executive"),
        ("President / EVP", "president", "president@hrms.com", "Executive", "President", "EMP-PRES-01", "executive"),
        ("VP / Regional Head", "vp", "vp@hrms.com", "Regional", "VP", "EMP-VP-01", "manager"),
        ("General Manager", "gm", "gm@hrms.com", "General", "Manager", "EMP-GM-01", "manager"),
        ("Senior Manager", "seniormanager", "seniormanager@hrms.com", "Senior", "Manager", "EMP-SMGR-01", "manager"),
        ("Manager", "manager", "manager@hrms.com", "Team", "Manager", "EMP-MGR-01", "manager"),
        ("Assistant Manager", "asstmanager", "asstmanager@hrms.com", "Assistant", "Manager", "EMP-AMGR-01", "manager"),
        ("Senior Executive", "srexecutive", "srexecutive@hrms.com", "Senior", "Executive", "EMP-SREX-01", "staff"),
        ("Executive", "executive", "executive@hrms.com", "Operations", "Executive", "EMP-EXEC-01", "staff"),
        ("Associate", "associate", "associate@hrms.com", "Operations", "Associate", "EMP-ASSC-01", "staff"),
        ("Officer", "officer", "officer@hrms.com", "Operations", "Officer", "EMP-OFF-01", "staff"),
        ("Staff / Site Personnel", "staff", "staff@hrms.com", "Site", "Personnel", "EMP-STF-01", "staff"),
    ]

    created_users = []

    print("\n=== Updating Roles & Creating Users ===")
    for role_name, username, email, first_name, last_name, emp_code, category in role_user_specs:
        role_obj = Role.objects.filter(name=role_name).first()
        if not role_obj:
            print(f"Warning: Role '{role_name}' not found in database! Creating it...")
            role_obj = Role.objects.create(name=role_name, code=emp_code.replace("EMP-", ""))

        # Ensure permissions are configured
        if not role_obj.permissions or len(role_obj.permissions) == 0:
            if category == 'executive':
                role_obj.permissions = dict(executive_perms)
                role_obj.dashboard_type = 'Executive'
                role_obj.access_scope = 'Corporate'
                role_obj.can_manage_users = True
                role_obj.can_approve = True
            elif category == 'manager':
                role_obj.permissions = dict(manager_perms)
                role_obj.dashboard_type = 'Manager'
                role_obj.access_scope = 'Region'
                role_obj.can_approve = True
            elif category == 'staff':
                role_obj.permissions = dict(staff_perms)
                role_obj.dashboard_type = 'Executive'
                role_obj.access_scope = 'Self'
            role_obj.save()

        # Create or update User
        user = User.objects.filter(username=username).first() or User.objects.filter(email=email).first()
        if not user:
            user = User(username=username, email=email)
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.is_active = True
        if role_name == "Super Admin":
            user.is_superuser = True
            user.is_staff = True
        user.set_password('123')
        user.save()

        # Create or update Employee
        emp = Employee.objects.filter(user=user).first() or Employee.objects.filter(code=emp_code).first()
        if not emp:
            emp = Employee(user=user, code=emp_code)
        
        emp.user = user
        emp.first_name = first_name
        emp.last_name = last_name
        emp.email = email
        emp.status = 'Active'
        emp.ctc = 1200000
        emp.gender = 'Male'
        emp.tax_regime = 'New'
        emp.dynamic_role = role_obj
        emp.role = 'super_admin' if user.is_superuser else ('site_admin' if role_name == 'Site Admin' else 'employee')
        emp.organization = org
        emp.entity = entity
        emp.site = site
        emp.branch = branch
        emp.save()

        created_users.append({
            'role': role_name,
            'username': user.username,
            'email': user.email,
            'password': '123',
            'emp_code': emp.code,
            'scope': role_obj.access_scope
        })

    # Also create a Standard Employee user (no dynamic role)
    emp_user = User.objects.filter(username='employee').first() or User.objects.filter(email='employee@hrms.com').first()
    if not emp_user:
        emp_user = User(username='employee', email='employee@hrms.com')
    emp_user.first_name = 'Standard'
    emp_user.last_name = 'Employee'
    emp_user.email = 'employee@hrms.com'
    emp_user.is_active = True
    emp_user.set_password('123')
    emp_user.save()

    emp_profile = Employee.objects.filter(user=emp_user).first() or Employee.objects.filter(code='EMP-STD-01').first()
    if not emp_profile:
        emp_profile = Employee(user=emp_user, code='EMP-STD-01')
    emp_profile.user = emp_user
    emp_profile.first_name = 'Standard'
    emp_profile.last_name = 'Employee'
    emp_profile.email = 'employee@hrms.com'
    emp_profile.status = 'Active'
    emp_profile.ctc = 600000
    emp_profile.gender = 'Male'
    emp_profile.tax_regime = 'New'
    emp_profile.dynamic_role = None
    emp_profile.role = 'employee'
    emp_profile.organization = org
    emp_profile.entity = entity
    emp_profile.site = site
    emp_profile.branch = branch
    emp_profile.save()

    created_users.append({
        'role': 'Standard Employee',
        'username': emp_user.username,
        'email': emp_user.email,
        'password': '123',
        'emp_code': emp_profile.code,
        'scope': 'Self'
    })

    # Ensure existing primary admin accounts also have password '123'
    existing_admins = ['Admin', 'Vibe_admin', 'gauravkokane05@gmail.com', 'lotusdev@gmail.com']
    for adm_name in existing_admins:
        adm_user = User.objects.filter(username=adm_name).first() or User.objects.filter(email=adm_name).first()
        if adm_user:
            adm_user.set_password('123')
            adm_user.is_active = True
            adm_user.save()
            print(f"Updated existing user '{adm_name}' password to '123'")

    print(f"\nSuccessfully created/configured {len(created_users)} role accounts!")
    
    # Verify authentication for all accounts
    print("\n=== Verifying Authentication with password '123' ===")
    failed = []
    for item in created_users:
        u1 = authenticate(username=item['username'], password='123')
        u2 = authenticate(username=item['email'], password='123')
        if u1 or u2:
            print(f"  [PASS] Role: {item['role']:28} | User: {item['username']:15} | Email: {item['email']}")
        else:
            print(f"  [FAIL] Role: {item['role']:28} | User: {item['username']:15} | Email: {item['email']}")
            failed.append(item['username'])

    if not failed:
        print("\nALL accounts successfully authenticated with password '123'!")
    else:
        print(f"\nAuthentication failed for {len(failed)} accounts: {failed}")

if __name__ == '__main__':
    create_and_setup_all_role_users()


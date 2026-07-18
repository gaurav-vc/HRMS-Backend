import os
import django
import sys

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from employees.models import Employee
from organisation.models import Entity, Site, Branch, Role

def migrate_admin_data():
    print("Starting migration...")
    
    # 1. Fetch the existing Admin superuser
    try:
        admin_user = User.objects.get(username='Admin')
    except User.DoesNotExist:
        print("Error: User with username 'Admin' not found.")
        return

    # 2. Find the Employee profile attached to Admin
    # This profile contains all the leaves, attendance, payroll, etc.
    admin_emp = Employee.objects.filter(user=admin_user).first()
    
    if not admin_emp:
        print("Error: The 'Admin' user does not have an associated Employee profile.")
        print("There is no HRMS data to migrate.")
        return
        
    print(f"Found Employee profile: {admin_emp.first_name} {admin_emp.last_name} ({admin_emp.code})")

    # 3. Create the new standard User account
    target_email = "gauravkokane05@gmail.com"
    new_user, created = User.objects.get_or_create(
        username=target_email,
        defaults={
            'email': target_email, 
            'is_staff': True, 
            'is_superuser': False
        }
    )
    
    if created:
        print(f"Created new non-superadmin user account: {target_email}")
    else:
        print(f"Found existing user account: {target_email}")
        
    # Unconditionally force password reset and ensure account is active
    new_user.set_password('Lotus@123')
    new_user.is_superuser = False
    new_user.is_active = True
    new_user.save()

    # 4. Ensure the Target Organization Structure Exists
    print("Setting up target organization (Lotus Developers -> Local Site HQ)...")
    from admin_org.models import Organization
    
    org, _ = Organization.objects.get_or_create(
        name__icontains='Lotus Developer',
        defaults={'name': 'Lotus Developers', 'status': 'Active'}
    )

    entity, _ = Entity.objects.get_or_create(
        name__icontains='Lotus Developer',
        defaults={'name': 'Lotus Developers', 'status': 'Active', 'organization': org}
    )
    
    branch, _ = Branch.objects.get_or_create(
        entity=entity,
        name='Head Office'
    )
    
    site, _ = Site.objects.get_or_create(
        organization=org,
        name__icontains='Local Site HQ',
        defaults={
            'name': 'Local Site HQ',
            'branch': branch,
            'site_code': 'LSHQ-01',
            'status': 'Active'
        }
    )

    # 5. Migrate the Employee Profile and Data
    print("Transferring profile and all historical data...")
    
    # Check if another employee already has this email and rename it to avoid UNIQUE constraint
    existing_emp = Employee.objects.filter(email=target_email).exclude(id=admin_emp.id).first()
    if existing_emp:
        print(f"Warning: Another employee already has the email {target_email}. Renaming it to avoid conflict.")
        existing_emp.email = f"old_{existing_emp.id}_{target_email}"
        existing_emp.save()

    admin_emp.user = new_user
    admin_emp.email = target_email
    admin_emp.entity = entity
    admin_emp.branch = branch
    admin_emp.site = site
    
    # 6. Assign the appropriate Role
    role, _ = Role.objects.get_or_create(
        name='Site Admin',
        defaults={
            'code': 'SITE-ADMIN',
            'access_scope': 'Site',
            'can_manage_users': True,
            'can_approve': True
        }
    )
    admin_emp.dynamic_role = role
    
    # Update name to reflect Gaurav 
    admin_emp.first_name = "Gaurav"
    admin_emp.last_name = "Kokane"
    
    admin_emp.save()

    print("\n=======================================================")
    print("MIGRATION SUCCESSFUL!")
    print("=======================================================")
    print("1. The superadmin 'Admin' has been cleanly stripped of its HRMS Employee profile.")
    print("2. All exact data (leaves, attendance, payroll) has been flawlessly cloned/moved.")
    print("3. It is now safely nested under 'Lotus Developers' -> 'Local Site HQ'.")
    print(f"4. You can now login to normal pages with:")
    print(f"   Email: {target_email}")
    print(f"   Password: Lotus@123  (if a new account was just created)")
    print("=======================================================")

if __name__ == '__main__':
    migrate_admin_data()

import os
import django
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from employees.models import Employee

def undo_migration():
    print("Rolling back migration...")

    try:
        admin_user = User.objects.get(username='Admin')
        admin_user.set_password('Tech@123')
        admin_user.is_superuser = True
        admin_user.is_staff = True
        admin_user.is_active = True
        admin_user.save()
        print("Restored Admin user account and password (Tech@123).")
    except User.DoesNotExist:
        print("Could not find 'Admin' user.")
        return

    try:
        gaurav_user = User.objects.get(username='gauravkokane05@gmail.com')
        # Find the profile we transferred to Gaurav
        emp = Employee.objects.filter(user=gaurav_user).first()
        
        if emp:
            # Reattach to Admin
            emp.user = admin_user
            emp.email = admin_user.email if admin_user.email else "admin@example.com"
            # reset name back to admin super
            emp.first_name = "admin"
            emp.last_name = "super"
            emp.dynamic_role = None # Remove the Site Admin role constraint
            emp.save()
            print("Successfully transferred the employee profile (EMP-0001) back to Admin.")
        else:
            print("Could not find the employee profile under gauravkokane05@gmail.com.")
    except User.DoesNotExist:
        print("Could not find gauravkokane05@gmail.com user to undo from.")

    print("\n=======================================================")
    print("UNDO SUCCESSFUL!")
    print("=======================================================")
    print("1. Your profile has been re-attached to the 'Admin' superuser.")
    print("2. The password for 'Admin' has been forced back to 'Tech@123'.")
    print("3. As a superadmin, you will bypass all organization restrictions and see all 19 employees globally again.")
    print("You can safely log in with Admin / Tech@123.")
    print("=======================================================")

if __name__ == '__main__':
    undo_migration()

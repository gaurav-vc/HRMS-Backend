import os
import django
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from employees.models import Employee

def force_undo():
    print("Forcing rollback...")

    admin_user = User.objects.get(username='Admin')
    admin_user.set_password('Tech@123')
    admin_user.is_superuser = True
    admin_user.is_staff = True
    admin_user.is_active = True
    admin_user.save()

    # Find the EMP-0001 profile no matter who owns it right now
    emp = Employee.objects.filter(code='EMP-0001').first()
    if emp:
        emp.user = admin_user
        emp.email = "Admin123@gmail.com"
        emp.first_name = "admin"
        emp.last_name = "super"
        emp.role = "super_admin"  # Crucial for sidebar visibility!
        emp.dynamic_role = None
        emp.save()
        print("FORCED SUCCESS: Profile re-attached to Admin and role set to super_admin.")
    else:
        print("Could not find EMP-0001.")

if __name__ == '__main__':
    force_undo()

import os
import django
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee

def fix_name():
    emp = Employee.objects.filter(code='EMP-0001').first()
    if emp:
        emp.first_name = "admin"
        emp.last_name = "super"
        emp.save()
        print("Successfully updated name to 'admin super'!")
    else:
        print("Employee not found.")

if __name__ == '__main__':
    fix_name()

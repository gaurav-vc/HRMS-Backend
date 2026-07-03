import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from payroll.models import SalaryStructure, PayrollRun

def main():
    # Delete old crashed or draft runs
    deleted_count, _ = PayrollRun.objects.filter(entity__name__icontains='Lotus').delete()
    print(f"Deleted {deleted_count} old payroll runs.")

    # Find the Client Structure
    struct = SalaryStructure.objects.filter(name__icontains='Client').first()
    if not struct:
        struct = SalaryStructure.objects.first()
    
    if not struct:
        print("No Salary Structure found in the database!")
        return

    # Assign it to Lotus employees
    emps = Employee.objects.filter(entity__name__icontains='Lotus')
    updated = emps.update(salary_structure=struct)
    print(f"Assigned '{struct.name}' to {updated} Lotus employees successfully!")

if __name__ == '__main__':
    main()

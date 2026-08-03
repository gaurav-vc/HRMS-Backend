import os
import django
import csv
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee

# Get the TATA employees
latest_employees = Employee.objects.filter(code__startswith='TATA').order_by('-created_at')

csv_file_path = r"c:\Users\MC VIP\OneDrive\Desktop\HRMS\backend\bulk_ctc_import.csv"

with open(csv_file_path, mode='w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow([
        'Employee ID', 'First Name', 'Last Name', 'Email', 
        'Department', 'Designation', 'CTC', 'Tax Regime', 
        'Tax Saving', 'Salary Structure', 'PF Applicable', 
        'Bonus Applicable', 'Bonus Type', 'Bonus Value', 
        'Bonus Month/Quarter'
    ])

    for emp in latest_employees:
        writer.writerow([
            emp.code,
            emp.first_name,
            emp.last_name,
            emp.email,
            emp.department.name if emp.department else '',
            emp.designation.title if emp.designation else '',
            emp.ctc,
            emp.tax_regime,
            emp.tax_saving_deductions,
            emp.salary_structure.name if emp.salary_structure else '',
            emp.pf_applicable,
            emp.bonus_applicable,
            emp.bonus_type if emp.bonus_type else '',
            emp.bonus_value,
            emp.bonus_months
        ])

print(f"Successfully wrote data to {csv_file_path}")

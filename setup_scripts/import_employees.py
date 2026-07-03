import os
import django
import csv
import sys
from datetime import datetime

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from organisation.models import Entity, Branch, Site, Department, Designation
from payroll.models import SalaryStructure

def parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), '%d-%m-%Y').date()
    except ValueError:
        return None

def import_csv(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            # 1. Get or Create Organizational Models
            entity_name = row.get('Entity', '').strip()
            entity = Entity.objects.get_or_create(name=entity_name)[0] if entity_name else None

            branch_name = row.get('Branch', '').strip()
            branch = Branch.objects.get_or_create(name=branch_name, entity=entity)[0] if branch_name and entity else None

            site_name = row.get('Site', '').strip()
            site = Site.objects.get_or_create(name=site_name, branch=branch)[0] if site_name and branch else None

            dept_name = row.get('Department', '').strip()
            department = Department.objects.get_or_create(name=dept_name, entity=entity)[0] if dept_name and entity else None

            desig_name = row.get('Designation', '').strip()
            designation = Designation.objects.get_or_create(title=desig_name, department=department)[0] if desig_name and department else None

            # Get Salary Structure (Assume it exists or leave None)
            struct_name = row.get('Salary Structure', '').strip()
            salary_structure = SalaryStructure.objects.filter(name=struct_name).first() if struct_name else None

            # 2. Check if Employee already exists by Code or Email
            emp_code = row.get('Employee Code', '').strip()
            email = row.get('Email', '').strip()
            
            if Employee.objects.filter(code=emp_code).exists() or Employee.objects.filter(email=email).exists():
                print(f"Skipping {emp_code} ({email}) - Already exists.")
                continue

            # 3. Create Employee
            try:
                ctc = int(row.get('CTC (Annual)', 0).strip())
            except ValueError:
                ctc = 0

            emp = Employee.objects.create(
                code=emp_code,
                first_name=row.get('First Name', '').strip(),
                last_name=row.get('Last Name', '').strip(),
                email=email,
                phone=row.get('Phone', '').strip(),
                dob=parse_date(row.get('Date of Birth', '')),
                gender=row.get('Gender', 'Male').strip(),
                address=row.get('Address', '').strip(),
                doj=parse_date(row.get('Date of Joining', '')),
                status=row.get('Status', 'Active').strip(),
                ctc=ctc,
                pan=row.get('PAN', '').strip(),
                aadhaar=row.get('Aadhaar', '').strip(),
                uan=row.get('UAN', '').strip(),
                esi=row.get('ESI No.', '').strip(),
                bank_name=row.get('Bank Name', '').strip(),
                ifsc=row.get('IFSC Code', '').strip(),
                bank_account=row.get('Bank Account No.', '').strip(),
                entity=entity,
                branch=branch,
                site=site,
                department=department,
                designation=designation,
                salary_structure=salary_structure
            )
            count += 1
            print(f"Successfully imported {emp.first_name} {emp.last_name} ({emp.code})")

    print(f"\nImport Complete! Successfully added {count} employees.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python import_employees.py <path_to_csv>")
    else:
        import_csv(sys.argv[1])

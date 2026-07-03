import os
import django
import csv
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from attendance.models import DailyAttendance
from organisation.models import Entity, Department, Designation, Site, Branch
from payroll.models import SalaryStructure

def run():
    print("Finding Lotus Developers entity...")
    entity = Entity.objects.filter(name__icontains='lotus').first()
    if not entity:
        entity = Entity.objects.create(name='Lotus Developers', type='Private')
        print("Created Lotus Developers entity.")

    print(f"Deleting all existing employees from {entity.name}...")
    Employee.objects.filter(entity=entity).delete()

    # Create basic department/site if missing
    dept, _ = Department.objects.get_or_create(name='General', entity=entity)
    branch, _ = Branch.objects.get_or_create(name='HQ', entity=entity)
    site, _ = Site.objects.get_or_create(name='HQ', branch=branch)
    
    # Fetch Client Structure
    client_structure = SalaryStructure.objects.filter(name__icontains='Client').first()

    # Data from image
    data = [
        # (Role, Name, Monthly, LOP, Late, OT)
        ('SENIOR MANAGER', 'Mukund Zujam', 120000, 2, 3, 3),
        ('EXECUTIVE', 'Vishal Tripathi', 60000, 1, 6, 0),
        ('SENIOR ARCHITECT', 'Hetal Karani', 220000, 3, 0, 3),
        ('ENGINEER', 'Dinesh Kumar', 50000, 31, 0, 0),
        ('ENGINEER', 'Rajnikant Deokar', 80000, 31, 0, 0),
        ('DRIVER', 'Naresh Kalluri', 25000, 0, 0, 0),
        ('ASSISTANT VICE PRESIDENT-PROCUREMENT', 'Jasmin Modi', 150000, 0, 0, 0),
    ]

    print("Generating new employees and their attendance for May 2026 (31 days)...")
    
    csv_data = []
    headers = [
        "Role", "Employee", "Monthly Salary", "Total Work Days (A)", 
        "No Of Leaves Applied (B)", "No Of Leaves Not Applied (C)", 
        "Net workDays A-(B+C)", "Payable Work Days A-C", 
        "Over time Hours", "No of Time Delay Deduction"
    ]
    csv_data.append(headers)

    start_date = datetime(2026, 5, 1).date()

    for idx, (role, name, monthly, lop, late, ot) in enumerate(data):
        # Create Designation
        desig, _ = Designation.objects.get_or_create(title=role, department=dept)

        first_name = name.split(' ')[0]
        last_name = ' '.join(name.split(' ')[1:]) if ' ' in name else ''

        # Generate missing details
        import random
        phone = f"98{random.randint(10000000, 99999999)}"
        pan = f"ABCDE{random.randint(1000, 9999)}F"
        aadhaar = f"{random.randint(100000000000, 999999999999)}"
        uan = f"100{random.randint(100000000, 999999999)}"
        esi = f"3100{random.randint(100000, 999999)}00001001"
        bank_acc = f"{random.randint(1000000000, 9999999999)}"
        
        # Create Employee
        emp = Employee.objects.create(
            code=f'LOTUS-{1000 + idx}',
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}@lotus.com",
            phone=phone,
            ctc=monthly * 12, # Annual CTC
            salary_structure=client_structure,
            employee_type='Normal Employee',
            bonus_applicable=True,
            bonus_type='Fixed Amount',
            bonus_value=random.randint(5000, 20000),
            pf_applicable=True,
            pan=pan,
            aadhaar=aadhaar,
            uan=uan,
            esi=esi,
            bank_name='HDFC Bank',
            bank_account=bank_acc,
            ifsc='HDFC0001234',
            entity=entity,
            department=dept,
            designation=desig,
            site=site,
            gender='Male' if name != 'Hetal Karani' else 'Female',
            doj='2025-01-01',
            dob='1990-01-01',
            status='Active'
        )

        # Generate Attendance for 31 days
        # We need to distribute `lop` Absents, `late` Lates, and `ot` Overtime hours.
        absent_left = lop
        late_left = late
        ot_left = ot

        for day in range(31):
            current_date = start_date + timedelta(days=day)
            
            status = 'Present'
            daily_ot = 0.0

            if absent_left > 0:
                status = 'Absent'
                absent_left -= 1
            elif late_left > 0:
                status = 'Late'
                late_left -= 1
            else:
                if ot_left > 0:
                    daily_ot = 1.0 # 1 hour of OT
                    ot_left -= 1

            check_in = datetime.combine(current_date, datetime.min.time().replace(hour=9, minute=0))
            check_out = datetime.combine(current_date, datetime.min.time().replace(hour=18, minute=0))

            DailyAttendance.objects.create(
                employee=emp,
                attendance_date=current_date,
                first_check_in=check_in if status != 'Absent' else None,
                last_check_out=check_out if status != 'Absent' else None,
                attendance_status=status,
                total_work_hours=9.0 if status != 'Absent' else 0.0,
                overtime_hours=daily_ot
            )

        # Build Excel Row Data
        delay_deduction = late / 3 * 0.5
        csv_row = [
            role,
            name,
            monthly,
            31, # A
            0,  # B
            lop, # C
            31 - (0 + lop), # Net workDays
            31 - lop, # Payable work days
            f"{ot} hours" if ot > 0 else "0",
            delay_deduction if delay_deduction > 0 else "0"
        ]
        csv_data.append(csv_row)
        
    # Write to CSV
    csv_path = os.path.join(os.getcwd(), 'lotus_employees.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(csv_data)

    print(f"Successfully generated employees, attendance, and saved Excel data to {csv_path}!")

if __name__ == '__main__':
    run()

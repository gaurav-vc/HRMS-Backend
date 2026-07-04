import os
import sys
import django
import csv
from datetime import date
import calendar
from decimal import Decimal

# Set up Django environment
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from django.db.models import Sum
from employees.models import Employee
from attendance.models import DailyAttendance
from payroll.models import Payslip

def generate_report():
    desktop_path = os.path.join(BASE_DIR, "Attendance_Payroll_Report.csv")
    
    today = date.today()
    period = today.strftime('%Y-%m')
    _, total_days = calendar.monthrange(today.year, today.month)
    
    with open(desktop_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Company', 'Region', 'Location', 'Group', 'Role', 'Employee',
            'Total Work Days (A)', 'Present Days', 'Absent Days', 
            'No Of Leaves (Applied)', 'No Of Leaves (Not Applied)', 
            'Net workDays', 'Payable Work Days', 'Overtime Hours', 
            'LOC / Time Delay Deduction', 'Annual Leave', 'In Hand Salary'
        ])
        
        employees = Employee.objects.select_related('entity', 'branch', 'site', 'department', 'designation').all()
        for emp in employees:
            company = emp.entity.name if emp.entity else ''
            region = emp.branch.name if emp.branch else 'India'
            location = emp.site.name if emp.site else ''
            group = emp.department.name if emp.department else ''
            role = emp.designation.name if emp.designation else ''
            emp_name = f"{emp.first_name} {emp.last_name}"
            
            attendances = DailyAttendance.objects.filter(
                employee=emp,
                attendance_date__year=today.year,
                attendance_date__month=today.month
            )
            
            present_days = attendances.filter(attendance_status='Present').count()
            absent_days = attendances.filter(attendance_status='Absent').count()
            leaves_applied = attendances.filter(attendance_status='Leave').count()
            leaves_not_applied = 0
            
            ot_sum = attendances.aggregate(Sum('overtime_hours'))['overtime_hours__sum']
            overtime = float(ot_sum) if ot_sum else 0.0
            
            net_workdays = total_days - (leaves_applied + leaves_not_applied)
            payable_workdays = net_workdays
            
            loc = 0
            annual_leave = 0
            
            payslip = Payslip.objects.filter(employee=emp, period=period).first()
            in_hand_salary = float(payslip.net) if payslip else 0.0
            
            writer.writerow([
                company, region, location, group, role, emp_name,
                total_days, present_days, absent_days,
                leaves_applied, leaves_not_applied,
                net_workdays, payable_workdays, overtime,
                loc, annual_leave, in_hand_salary
            ])
            
    print(f"Report generated successfully at {desktop_path}")

if __name__ == '__main__':
    generate_report()

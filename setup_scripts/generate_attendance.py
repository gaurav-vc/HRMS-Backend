import os
import django
import random
from datetime import date, timedelta, datetime

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from attendance.models import DailyAttendance

def generate_random_attendance(year=2026, month=6):
    employees = Employee.objects.all()
    if not employees.exists():
        print("No employees found. Please import employees first.")
        return

    # Delete existing attendance for the month to avoid duplicates if run multiple times
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
        
    DailyAttendance.objects.filter(attendance_date__range=[start_date, end_date]).delete()

    # Generate all days in the month
    all_days = []
    current_day = start_date
    while current_day <= end_date:
        # Exclude Sundays just for realism
        if current_day.weekday() != 6:
            all_days.append(current_day)
        current_day += timedelta(days=1)

    count = 0
    for emp in employees:
        # Randomly choose between 15 and 20 days of attendance
        target_days = random.randint(15, min(20, len(all_days)))
        
        # Randomly select which exact dates they were present
        present_dates = random.sample(all_days, target_days)
        
        # Create records
        for p_date in present_dates:
            from zoneinfo import ZoneInfo
            ist = ZoneInfo("Asia/Kolkata")
            
            status = 'Present'
            hours = 8.0
            check_in_hour = 10
            check_in_min = 0
            check_out_hour = 18
            
            rand_val = random.random()
            if rand_val < 0.15:
                # 15% chance of being Late
                status = 'Late'
                check_in_min = random.randint(30, 59) # Check in between 10:30 and 10:59
            elif rand_val < 0.25:
                # 10% chance of Half Day
                status = 'Half Day'
                check_out_hour = 14 # Check out at 2:00 PM
                hours = 4.0
            
            # Generate check-in and check-out
            check_in_time = datetime.combine(p_date, datetime.min.time()).replace(tzinfo=ist) + timedelta(hours=check_in_hour, minutes=check_in_min)
            check_out_time = datetime.combine(p_date, datetime.min.time()).replace(tzinfo=ist) + timedelta(hours=check_out_hour)
            
            DailyAttendance.objects.create(
                employee=emp,
                site=emp.site,
                organization=emp.entity,
                attendance_date=p_date,
                first_check_in=check_in_time,
                last_check_out=check_out_time,
                attendance_status=status,
                total_work_hours=hours
            )
        count += target_days
        print(f"Generated {target_days} present days for {emp.first_name} {emp.last_name}")

    print(f"\nSuccessfully generated {count} total attendance records for {year}-{month:02d}!")

if __name__ == '__main__':
    generate_random_attendance(year=2026, month=6)

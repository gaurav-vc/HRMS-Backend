import os
import sys
import django
from datetime import date, timedelta
import random

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from attendance.models import DailyAttendance
from django.utils import timezone
from datetime import time

def generate_specific_attendance():
    # Add any employee emails you want to generate attendance for here!
    target_emails = [
        "tikihi8356@neplis.com",
        "bagem45024@meikeya.com",  # You can add Raj Patil's email here if you know it!
    ]
    
    # Dates: June 1, 2026 to July 31, 2026
    start_date = date(2026, 6, 1)
    end_date = date(2026, 7, 31)
    delta = end_date - start_date
    all_dates = [start_date + timedelta(days=i) for i in range(delta.days + 1)]

    for target_email in target_emails:
        try:
            emp = Employee.objects.get(email=target_email)
        except Employee.DoesNotExist:
            print(f"Error: Could not find employee with email {target_email}")
            continue
        
        created_count = 0
        updated_count = 0

        for current_date in all_dates:
            # Skip Sundays (6)
            if current_date.weekday() == 6:
                continue
                
            is_late = random.random() < 0.15
            is_half_day = random.random() < 0.05
            is_overtime = random.random() < 0.10
            
            if is_late:
                check_in_time = time(random.randint(9, 10), random.randint(16, 59))
            else:
                check_in_time = time(8, random.randint(30, 59))
                
            if is_half_day:
                check_out_time = time(13, random.randint(0, 30))
            elif is_overtime:
                check_out_time = time(random.randint(19, 21), random.randint(0, 59))
            else:
                check_out_time = time(random.randint(17, 18), random.randint(0, 59))
                
            check_in_dt = timezone.make_aware(timezone.datetime.combine(current_date, check_in_time))
            check_out_dt = timezone.make_aware(timezone.datetime.combine(current_date, check_out_time))
            
            att, created = DailyAttendance.objects.update_or_create(
                employee=emp,
                attendance_date=current_date,
                defaults={
                    'first_check_in': check_in_dt,
                    'last_check_out': check_out_dt,
                    'attendance_status': 'Present',
                    'site': emp.site,
                    'organization': emp.entity
                }
            )
            
            if created:
                created_count += 1
            else:
                updated_count += 1
                
        print(f"Success! Generated {created_count} new attendance records and updated {updated_count} for {emp.first_name} {emp.last_name} ({emp.email}).")

if __name__ == '__main__':
    generate_specific_attendance()

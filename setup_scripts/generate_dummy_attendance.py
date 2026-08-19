import os
import sys
import django
import random
from datetime import date, timedelta, datetime

# Add the parent directory (backend root) to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from employees.models import Employee
from attendance.models import DailyAttendance
from organisation.models import Site

def main():
    # Only target Lotus HQ related emails or sites
    lotus_hq = Site.objects.filter(name__icontains="Lotus HQ").first()
    if not lotus_hq:
        print("Lotus HQ site not found.")
        return
        
    print(f"Targeting employees in Site: {lotus_hq.name}")
    
    # Target emails provided by user
    target_emails = [
        "mukund.zujam@lotushq.com",
        "vishal.tripathi@lotushq.com",
        "hetal.karani@lotushq.com",
        "dinesh.kumar@lotushq.com",
        "rajnikant.deokar@lotushq.com",
        "naresh.kalluri@lotushq.com",
        "jasmin.modi@lotushq.com",
        "arvohra87@gmail.com",
        "gauravkokane05@gmail.com",
        "tikihil8356@neplis.com"
    ]
    
    employees = Employee.objects.filter(email__in=target_emails)
    print(f"Found {employees.count()} employees out of {len(target_emails)}.")
    
    # Dates: June 1, 2026 to August 31, 2026
    start_date = date(2026, 6, 1)
    end_date = date(2026, 8, 31)
    
    delta = end_date - start_date
    all_dates = [start_date + timedelta(days=i) for i in range(delta.days + 1)]
    
    from datetime import time
    shift_start_time = time(9, 0)
    shift_end_time = time(18, 0) # 9 hours
    
    records_created = 0
    records_updated = 0
    
    for emp in employees:
        for d in all_dates:
            # Skip Sundays
            if d.weekday() == 6:
                continue
                
            is_present = random.random() < 0.85
            
            if is_present:
                has_ot = random.random() < 0.30
                ot_hours = random.randint(1, 4) if has_ot else 0
                
                check_in_dt = datetime.combine(d, shift_start_time)
                check_out_dt = datetime.combine(d, shift_end_time) + timedelta(hours=ot_hours)
                status = 'Present'
            else:
                check_in_dt = None
                check_out_dt = None
                status = 'Absent'
            
            site_to_use = emp.site if emp.site else lotus_hq
            org_to_use = emp.entity if emp.entity else (site_to_use.entity if hasattr(site_to_use, 'entity') else None)
            
            att, created = DailyAttendance.objects.update_or_create(
                employee=emp,
                attendance_date=d,
                defaults={
                    'site': site_to_use,
                    'organization': org_to_use,
                    'first_check_in': check_in_dt,
                    'last_check_out': check_out_dt,
                    'attendance_status': status
                }
            )
            # The model's save() will automatically compute total_work_hours and overtime_hours.
            if created:
                records_created += 1
            else:
                records_updated += 1

    print(f"Generated {records_created} new dummy attendance records. Updated {records_updated}.")

if __name__ == '__main__':
    main()

import os
import django
from datetime import date, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from attendance.models import DailyAttendance
from leaves.models import LeaveRequest, LeaveType

def main():
    attendance_data = {
        'Mukund': {'present': 29, 'lop': 2},
        'Vishal': {'present': 30, 'lop': 1},
        'Hetal': {'present': 28, 'lop': 3},
        'Dinesh': {'present': 0, 'lop': 31},
        'Rajnikant': {'present': 0, 'lop': 31},
        'Naresh': {'present': 31, 'lop': 0},
        'Jasmin': {'present': 31, 'lop': 0},
    }
    
    # We are fixing attendance for June 2026 to match the UI preview
    start_date = date(2026, 6, 1)
    
    for first_name, data in attendance_data.items():
        emp = Employee.objects.filter(first_name__icontains=first_name, entity__name__icontains='Lotus').first()
        if not emp:
            print(f"Could not find employee: {first_name}")
            continue
            
        # Delete old attendance
        DailyAttendance.objects.filter(employee=emp, attendance_date__year=2026, attendance_date__month=6).delete()
        LeaveRequest.objects.filter(employee=emp, start_date__year=2026, start_date__month=6).delete()
        
        present_days = data['present']
        lop_days = data['lop']
        
        # Create present days
        for i in range(present_days):
            att_date = start_date + timedelta(days=i)
            DailyAttendance.objects.create(
                employee=emp,
                attendance_date=att_date,
                attendance_status='Present',
                first_check_in=f"{att_date} 09:00:00",
                last_check_out=f"{att_date} 18:00:00"
            )
            
        # Create LOP days as leave requests
        if lop_days > 0:
            lop_start = start_date + timedelta(days=present_days)
            lop_end = lop_start + timedelta(days=lop_days - 1)
            
            lop_type, _ = LeaveType.objects.get_or_create(
                name='Loss of Pay',
                defaults={'code': 'LOP', 'annual_entitlement': 0.0}
            )
            
            LeaveRequest.objects.create(
                employee=emp,
                leave_type=lop_type,
                sub_type='Other',
                start_date=lop_start,
                end_date=lop_end,
                total_days=lop_days,
                salary_deduction_days=lop_days,
                reason='LOP automatically applied from system',
                status='Approved'
            )
            
        print(f"Updated {first_name}: {present_days} Present, {lop_days} LOP")

if __name__ == '__main__':
    main()

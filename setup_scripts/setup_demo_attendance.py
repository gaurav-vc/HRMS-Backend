import os
import django
from datetime import date, timedelta, datetime
from django.utils import timezone
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from attendance.models import DailyAttendance

def setup_demo():
    print("Setting up Demo Attendance for Mukund, Hetal, and Vishal...")
    start_date = date(2026, 6, 1)

    # Clean old attendance for these three
    for name in ['Mukund', 'Hetal', 'Vishal']:
        emp = Employee.objects.filter(first_name__icontains=name, entity__name__icontains='Lotus').first()
        if not emp: continue
        DailyAttendance.objects.filter(employee=emp, attendance_date__year=2026, attendance_date__month=6).delete()
    
    # 1. MUKUND
    mukund = Employee.objects.filter(first_name__icontains='Mukund').first()
    if mukund:
        for i in range(25): # 25 present days
            d = start_date + timedelta(days=i)
            is_late = i < 3 # First 3 days are Late
            has_ot = 3 <= i < 6 # Next 3 days have 1 hour OT each
            
            status = 'Late' if is_late else 'Present'
            ot_hours = Decimal('1.00') if has_ot else Decimal('0.00')
            
            start_str = "09:30:00" if is_late else "09:00:00"
            end_str = "20:00:00" if has_ot else "18:00:00"
            
            in_dt = timezone.make_aware(datetime.strptime(f"{d} {start_str}", "%Y-%m-%d %H:%M:%S"))
            out_dt = timezone.make_aware(datetime.strptime(f"{d} {end_str}", "%Y-%m-%d %H:%M:%S"))
            
            DailyAttendance.objects.create(
                employee=mukund,
                attendance_date=d,
                attendance_status=status,
                first_check_in=in_dt,
                last_check_out=out_dt,
                overtime_hours=ot_hours,
                total_work_hours=Decimal('8.00') + ot_hours
            )
        print("Mukund: Added 25 present days (3 Late punches, 3 days with 3 hr OT)")

    # 2. HETAL
    hetal = Employee.objects.filter(first_name__icontains='Hetal').first()
    if hetal:
        for i in range(25): 
            d = start_date + timedelta(days=i)
            has_ot = i < 3 # First 3 days have 1 hour OT each
            
            ot_hours = Decimal('3.00') if has_ot else Decimal('0.00')
            end_str = "20:00:00" if has_ot else "18:00:00"
            
            in_dt = timezone.make_aware(datetime.strptime(f"{d} 09:00:00", "%Y-%m-%d %H:%M:%S"))
            out_dt = timezone.make_aware(datetime.strptime(f"{d} {end_str}", "%Y-%m-%d %H:%M:%S"))
            
            DailyAttendance.objects.create(
                employee=hetal,
                attendance_date=d,
                attendance_status='Present',
                first_check_in=in_dt,
                last_check_out=out_dt,
                overtime_hours=ot_hours,
                total_work_hours=Decimal('8.00') + ot_hours
            )
        print("Hetal: Added 25 present days (3 days with 3 hr OT)")

    # 3. VISHAL
    vishal = Employee.objects.filter(first_name__icontains='Vishal').first()
    if vishal:
        for i in range(25): 
            d = start_date + timedelta(days=i)
            is_late = i < 6 # First 6 days are Late
            
            status = 'Late' if is_late else 'Present'
            start_str = "09:30:00" if is_late else "09:00:00"
            
            in_dt = timezone.make_aware(datetime.strptime(f"{d} {start_str}", "%Y-%m-%d %H:%M:%S"))
            out_dt = timezone.make_aware(datetime.strptime(f"{d} 18:00:00", "%Y-%m-%d %H:%M:%S"))
            
            DailyAttendance.objects.create(
                employee=vishal,
                attendance_date=d,
                attendance_status=status,
                first_check_in=in_dt,
                last_check_out=out_dt,
                overtime_hours=Decimal('0.00'),
                total_work_hours=Decimal('8.00')
            )
        print("Vishal: Added 25 present days (6 Late punches)")

    print("Demo data injected successfully!")

if __name__ == '__main__':
    setup_demo()

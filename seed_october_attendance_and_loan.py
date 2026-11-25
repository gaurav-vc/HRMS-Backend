import os
import django
from datetime import date, datetime, time, timedelta
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from attendance.models import DailyAttendance, Holiday
from leaves.models import LeaveRequest, LeaveType
from payroll.models import Loan, LoanInstallment, SalaryAdvance

def seed_october():
    print("=" * 60)
    print("SEEDING OCTOBER 2026 ATTENDANCE, LEAVES & LOAN SCHEDULE")
    print("=" * 60)

    # 1. Setup Holidays in October 2026
    Holiday.objects.filter(date__year=2026, date__month=10).delete()
    h1, _ = Holiday.objects.get_or_create(name="Gandhi Jayanti", date=date(2026, 10, 2), defaults={"description": "National Holiday"})
    h2, _ = Holiday.objects.get_or_create(name="Dussehra", date=date(2026, 10, 20), defaults={"description": "Festival Holiday"})
    holiday_dates = {date(2026, 10, 2), date(2026, 10, 20)}
    print(f"Configured October Holidays: 2026-10-02 (Gandhi Jayanti), 2026-10-20 (Dussehra)")

    # 2. Get standard Leave Types
    al_type = LeaveType.objects.filter(name__icontains="Annual").first()
    if not al_type:
        al_type = LeaveType.objects.create(name="Annual Leave", code="AL", annual_entitlement=12.0)

    lop_type = LeaveType.objects.filter(name__icontains="Loss of Pay").first() or LeaveType.objects.filter(name__icontains="LOP").first()
    if not lop_type:
        lop_type = LeaveType.objects.create(name="Loss of Pay", code="LOP", annual_entitlement=0.0)

    # 3. Clean existing October attendance & leave requests
    DailyAttendance.objects.filter(attendance_date__year=2026, attendance_date__month=10).delete()
    LeaveRequest.objects.filter(start_date__lte=date(2026, 10, 31), end_date__gte=date(2026, 10, 1)).delete()
    print("Cleaned existing October 2026 attendance and leave records.")

    # 4. Configure Loan #6 for Dinesh Kumar (EMP-1004) to start in October 2026
    dinesh = Employee.objects.filter(code="EMP-1004").first()
    if dinesh:
        loan = Loan.objects.filter(employee=dinesh, status="Active").first()
        if not loan:
            loan = Loan.objects.filter(id=6).first()
        if loan:
            loan.start_period = "2026-10"
            loan.outstanding = Decimal("100000.00")
            loan.status = "Active"
            loan.save()
            loan.generate_schedule()
            print(f"Updated Loan #{loan.id} for {dinesh.first_name} {dinesh.last_name}: start_period='2026-10', schedule regenerated starting at 2026-10 (EMI: {loan.emi})")

    # 5. Define Employees and their Scenarios for October 2026
    employees = Employee.objects.all()

    # Dates breakdown for October 2026 (31 days: 1 to 31)
    # Total days = 31
    # Sundays: Oct 4, 11, 18, 25 (4 Sundays)
    # Holidays: Oct 2, 20 (2 Holidays)
    # Working Days = 31 - 4 - 2 = 25 days

    oct_dates = [date(2026, 10, d) for d in range(1, 32)]

    for emp in employees:
        code = emp.code
        # Default settings for each employee
        lop_dates = set()
        paid_leave_dates = set()
        half_day_dates = set()
        late_dates = set()
        ot_days_map = {} # date -> ot_hours

        if code == "EMP-1004":
            # Dinesh Kumar: Featured Employee with Loan + LOP + OT + Half Day + Late
            # LOP: 4 days (Oct 13, 14, 15, 16)
            lop_dates = {date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)}
            # Half days: 2 days (Oct 7, 22)
            half_day_dates = {date(2026, 10, 7), date(2026, 10, 22)}
            # Late marks: 3 days (Oct 5, 8, 12)
            late_dates = {date(2026, 10, 5), date(2026, 10, 8), date(2026, 10, 12)}
            # Overtime: 16 hours total (2.0 hours OT on 8 days: Oct 6, 9, 19, 21, 23, 26, 27, 28)
            for d in [6, 9, 19, 21, 23, 26, 27, 28]:
                ot_days_map[date(2026, 10, d)] = Decimal("2.00")

        elif code == "LD0294":
            # Murugan Arumugam: Overtime Star (24.0 hours OT)
            # 0 LOP, 0 absences, 0 half days
            # Worked 12 days with 2.0 hours OT each = 24.0 hours OT!
            for d in [5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 21]:
                ot_days_map[date(2026, 10, d)] = Decimal("2.00")

        elif code == "EMP-1005":
            # Rajnikant Deokar: Late marks & 2 LOP days
            lop_dates = {date(2026, 10, 8), date(2026, 10, 9)}
            half_day_dates = {date(2026, 10, 14), date(2026, 10, 23)}
            late_dates = {date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 12), date(2026, 10, 15), date(2026, 10, 19)}

        elif code == "EMP-1006":
            # Naresh Kalluri: Paid Leave (2 days AL) + LOP (3 days) + 8h OT
            paid_leave_dates = {date(2026, 10, 5), date(2026, 10, 6)}
            lop_dates = {date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)}
            for d in [7, 8, 9, 12]:
                ot_days_map[date(2026, 10, d)] = Decimal("2.00")

        elif code == "EMP-22119":
            # Paras Desai: Perfect Month Baseline (Full present, no OT, no LOP)
            pass

        elif code == "LD0293":
            # Apurva Ajay Petkar: 3 days Paid Annual Leave
            paid_leave_dates = {date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)}

        elif code == "LD0288":
            # Manuraj Esakimuthu: Heavy LOP (6 days LOP)
            lop_dates = {date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)}

        # Seed approved leave requests for LOP
        if lop_dates:
            sorted_lop = sorted(list(lop_dates))
            lr = LeaveRequest.objects.create(
                employee=emp,
                entity=emp.entity,
                organization=getattr(emp, "organization", None),
                site=emp.site,
                leave_type=lop_type,
                sub_type="LOP",
                start_date=sorted_lop[0],
                end_date=sorted_lop[-1],
                total_days=Decimal(len(lop_dates)),
                salary_deduction_days=Decimal(len(lop_dates)),
                reason="Personal leave without pay",
                status="Approved",
                manager_comments="Approved with loss of pay deduction",
                approved_by="HR Manager",
                approved_at=datetime(2026, 10, 1, 10, 0)
            )

        # Seed approved leave requests for Paid Leaves
        if paid_leave_dates:
            sorted_pl = sorted(list(paid_leave_dates))
            lr = LeaveRequest.objects.create(
                employee=emp,
                entity=emp.entity,
                organization=getattr(emp, "organization", None),
                site=emp.site,
                leave_type=al_type,
                sub_type="PAID",
                start_date=sorted_pl[0],
                end_date=sorted_pl[-1],
                total_days=Decimal(len(paid_leave_dates)),
                salary_deduction_days=Decimal("0.00"),
                reason="Annual vacation leave",
                status="Approved",
                manager_comments="Annual leave approved with pay",
                approved_by="HR Manager",
                approved_at=datetime(2026, 10, 1, 10, 0)
            )

        # Create daily attendance records for all 31 days
        for cur_d in oct_dates:
            is_sunday = cur_d.weekday() == 6
            is_holiday = cur_d in holiday_dates
            is_lop = cur_d in lop_dates
            is_paid_leave = cur_d in paid_leave_dates
            is_half_day = cur_d in half_day_dates
            is_late = cur_d in late_dates
            ot_h = ot_days_map.get(cur_d, Decimal("0.00"))

            if is_sunday:
                status_str = "Weekly Off"
                work_h = Decimal("0.00")
                ot_h = Decimal("0.00")
                in_time = None
                out_time = None
            elif is_holiday:
                status_str = "Holiday"
                work_h = Decimal("0.00")
                ot_h = Decimal("0.00")
                in_time = None
                out_time = None
            elif is_lop:
                status_str = "Absent"
                work_h = Decimal("0.00")
                ot_h = Decimal("0.00")
                in_time = None
                out_time = None
            elif is_paid_leave:
                status_str = "On Leave"
                work_h = Decimal("0.00")
                ot_h = Decimal("0.00")
                in_time = None
                out_time = None
            elif is_half_day:
                status_str = "Half Day"
                work_h = Decimal("4.50")
                in_time = datetime.combine(cur_d, time(9, 30))
                out_time = datetime.combine(cur_d, time(14, 0))
            elif is_late:
                status_str = "Late"
                work_h = Decimal("8.00")
                in_time = datetime.combine(cur_d, time(10, 15)) # 45 mins late
                out_time = datetime.combine(cur_d, time(18, 45))
            else:
                status_str = "Present"
                work_h = Decimal("8.00") + ot_h
                in_time = datetime.combine(cur_d, time(9, 30))
                out_time = datetime.combine(cur_d, time(18, 0)) if ot_h == 0 else datetime.combine(cur_d, time(20, 0))

            DailyAttendance.objects.create(
                employee=emp,
                entity=emp.entity,
                organization=getattr(emp, "organization", None),
                site=emp.site,
                attendance_date=cur_d,
                attendance_status=status_str,
                first_check_in=in_time,
                last_check_out=out_time,
                total_work_hours=work_h,
                overtime_hours=ot_h,
                late_deduction_amount=Decimal("0.00"),
                is_approved=True
            )

    print("Successfully seeded October 2026 attendance and leave requests for all employees.")

if __name__ == "__main__":
    seed_october()

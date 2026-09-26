from django.core.management.base import BaseCommand
from datetime import date, datetime, time, timedelta
from django.utils import timezone
from employees.models import Employee
from organisation.models import Site, Entity
from admin_org.models import Organization
from attendance.models import DailyAttendance, PunchLog, ShiftDefinition, ShiftAssignment

class Command(BaseCommand):
    help = 'Populates dummy attendance data for testing CSV export'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting attendance data population...")
        
        org = Organization.objects.first()
        if not org:
            org = Organization.objects.create(name="Test Org")
        
        entity = Entity.objects.first()
        if not entity:
            entity = Entity.objects.create(name="Test Entity", organization=org)
            
        site = Site.objects.first()
        if not site:
            site = Site.objects.create(name="Test Site", organization=org)
        
        shift, created = ShiftDefinition.objects.get_or_create(
            code="GEN",
            defaults={
                "name": "General",
                "site": site,
                "start_time": time(9, 30),
                "end_time": time(18, 30),
                "grace_minutes": 15,
            }
        )
        self.stdout.write(f"Using Shift: {shift.name} ({shift.start_time} - {shift.end_time})")

        employees = list(Employee.objects.filter(status='Active')[:4])
        while len(employees) < 4:
            code = f"TEST-EMP-{len(employees)+1}"
            emp = Employee.objects.create(
                code=code,
                first_name=f"Test",
                last_name=f"User {len(employees)+1}",
                email=f"{code.lower()}@example.com",
                organization=org,
                entity=entity,
                site=site
            )
            employees.append(emp)
        
        test_date = date(2026, 9, 20)
        self.stdout.write(f"Populating data for Date: {test_date}")
        
        scenarios = [
            {"emp": employees[0], "desc": "Early + OT", "in": time(9, 10), "out": time(19, 30), "status": "Present", "ot": 1.0},
            {"emp": employees[1], "desc": "Late Coming", "in": time(10, 15), "out": time(18, 30), "status": "Present", "ot": 0.0},
            {"emp": employees[2], "desc": "On Time", "in": time(9, 30), "out": time(18, 30), "status": "Present", "ot": 0.0},
            {"emp": employees[3], "desc": "Absent", "in": None, "out": None, "status": "Absent", "ot": 0.0},
        ]
        
        for scenario in scenarios:
            emp = scenario["emp"]
            
            ShiftAssignment.objects.update_or_create(
                employee=emp, date=test_date,
                defaults={"shift": shift}
            )
            
            if scenario["in"] and scenario["out"]:
                in_dt = timezone.make_aware(datetime.combine(test_date, scenario["in"]))
                out_dt = timezone.make_aware(datetime.combine(test_date, scenario["out"]))
                
                diff = (out_dt - in_dt).total_seconds()
            else:
                in_dt = None
                out_dt = None
                
            att, _ = DailyAttendance.objects.update_or_create(
                employee=emp,
                attendance_date=test_date,
                defaults={
                    "first_check_in": in_dt,
                    "last_check_out": out_dt,
                    "attendance_status": scenario["status"],
                    "site": site,
                    "organization": entity
                }
            )
            
            if in_dt and out_dt:
                PunchLog.objects.filter(daily_attendance=att).delete()
                PunchLog.objects.create(
                    employee=emp, daily_attendance=att,
                    punch_time=in_dt, punch_type="IN", source="FACE",
                    verification_status="VERIFIED"
                )
                PunchLog.objects.create(
                    employee=emp, daily_attendance=att,
                    punch_time=out_dt, punch_type="OUT", source="FACE",
                    verification_status="VERIFIED"
                )
                
            self.stdout.write(f"Created data for {emp.first_name}: {scenario['desc']}")

        self.stdout.write(self.style.SUCCESS("Success! Data populated. Please check September 20, 2026 on your Attendance page."))

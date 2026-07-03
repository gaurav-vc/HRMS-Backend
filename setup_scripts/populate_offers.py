import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import OfferLetter, OfferTemplate, Employee
from datetime import date, timedelta

print("Clearing old templates...")
OfferTemplate.objects.all().delete()

print("Creating Templates...")
OfferTemplate.objects.create(
    name="Graduate Hire - India",
    category="GRADUATE HIRE",
    placeholders=["EmployeeName", "Designation", "Department", "JoiningDate", "CTC", "NoticePeriod"]
)
OfferTemplate.objects.create(
    name="Experienced Hire",
    category="EXPERIENCED HIRE",
    placeholders=["EmployeeName", "Designation", "Department", "JoiningDate", "CTC"]
)
OfferTemplate.objects.create(
    name="Site Worker - GCC",
    category="SITE WORKER",
    placeholders=["EmployeeName", "Designation", "JoiningDate", "WorkLocation"]
)

# Employees for dummy data
print("Creating dummy offer letters for existing employees...")
employees = list(Employee.objects.all()[:3])
if employees:
    for i, emp in enumerate(employees):
        OfferLetter.objects.filter(employee=emp).delete()
        if i == 0:
            OfferLetter.objects.create(employee=emp, offer_number="OFF-2026-0001", status="Pending Approval", joining_date=date(2026, 8, 1))
        elif i == 1:
            OfferLetter.objects.create(employee=emp, offer_number="OFF-2026-0002", status="Awaiting Acceptance", joining_date=date(2026, 7, 15))
        elif i == 2:
            OfferLetter.objects.create(employee=emp, offer_number="OFF-2026-0003", status="Draft", joining_date=date(2026, 9, 10))
else:
    print("Warning: No employees found in the database. Creating a dummy employee first...")
    user = django.contrib.auth.models.User.objects.create_user(username="dummy", email="dummy@acme.co", password="password")
    emp = Employee.objects.create(user=user, first_name="Dummy", last_name="User", code="DUM-01", email="dummy@acme.co")
    OfferLetter.objects.create(employee=emp, offer_number="OFF-2026-0001", status="Pending Approval", joining_date=date(2026, 8, 1))

print("Done!")

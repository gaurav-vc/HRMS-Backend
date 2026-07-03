import os
import django
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from organisation.models import Entity
from payroll.models import ComponentRule, Loan, Reimbursement, PayrollRun

print("Creating dummy payroll data...")

# Get or create an employee
emp = Employee.objects.first()
entity = Entity.objects.first()

if not emp or not entity:
    print("Please run seed_db.py first to create an Employee and Entity!")
    exit(1)

# 1. Salary Components
ComponentRule.objects.all().delete()
components = [
    {"name": "Basic Pay", "type": "Earning", "formula": "ctc * (40 / 100)"},
    {"name": "HRA", "type": "Earning", "formula": "basic * (50 / 100)"},
    {"name": "Medical Allowance", "type": "Earning", "formula": "1500"},
    {"name": "Provident Fund", "type": "Deduction", "formula": "basic * (12 / 100)"},
    {"name": "Professional Tax", "type": "Deduction", "formula": "200"},
]
from datetime import date
for comp in components:
    ComponentRule.objects.get_or_create(name=comp['name'], defaults={**comp, 'effective_from': date(2026, 1, 1)})
print("Created 5 Component Rules.")

# 2. Loans
loans = [
    {"type": "Personal", "amount": 100000, "emi": 5000, "tenure": 20, "outstanding": 80000, "status": "Active"},
    {"type": "Education", "amount": 200000, "emi": 10000, "tenure": 20, "outstanding": 150000, "status": "Active"},
    {"type": "Salary Advance", "amount": 25000, "emi": 5000, "tenure": 5, "outstanding": 5000, "status": "Active"},
    {"type": "Medical Emergency", "amount": 50000, "emi": 10000, "tenure": 5, "outstanding": 0, "status": "Closed"},
    {"type": "Home Renovation", "amount": 300000, "emi": 15000, "tenure": 20, "outstanding": 300000, "status": "Pending"},
]
for loan_data in loans:
    Loan.objects.get_or_create(employee=emp, type=loan_data['type'], defaults=loan_data)
print("Created 5 Loans.")

# 3. Reimbursements
reimbursements = [
    {"category": "Travel", "amount": 4500, "date": date(2026, 6, 1), "status": "Approved"},
    {"category": "Meals", "amount": 800, "date": date(2026, 6, 5), "status": "Paid"},
    {"category": "Internet", "amount": 1200, "date": date(2026, 6, 10), "status": "Pending"},
    {"category": "Medical", "amount": 3500, "date": date(2026, 6, 12), "status": "Rejected"},
    {"category": "Office Supplies", "amount": 2000, "date": date(2026, 6, 15), "status": "Pending"},
]
for reimb_data in reimbursements:
    Reimbursement.objects.get_or_create(employee=emp, category=reimb_data['category'], defaults=reimb_data)
print("Created 5 Reimbursements.")

# 4. Payroll Runs
PayrollRun.objects.all().delete()
runs = [
    {"period": "2026-02", "status": "Disbursed"},
    {"period": "2026-03", "status": "Disbursed"},
    {"period": "2026-04", "status": "Disbursed"},
    {"period": "2026-05", "status": "Disbursed"},
    {"period": "2026-06", "status": "Draft"},
]
for run_data in runs:
    PayrollRun.objects.get_or_create(entity=entity, period=run_data['period'], defaults=run_data)
print("Created 5 Payroll Runs.")

print("Dummy data successfully seeded!")

import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from leaves.models import LeaveType, LeaveBalance, LeaveRequest
from employees.models import Employee
from django.utils import timezone
from datetime import timedelta, date

# Let's see if there is any AL leave type
try:
    al_type = LeaveType.objects.get(code='AL')
except LeaveType.DoesNotExist:
    print("No AL leave type found.")
    sys.exit(0)

# Let's get an employee with some AL balance
balances = LeaveBalance.objects.filter(leave_type=al_type, remaining_days__gt=0)
if not balances.exists():
    print("No employee with AL balance found.")
    sys.exit(0)

balance = balances.first()
employee = balance.employee

print(f"Employee: {employee.user.username if employee.user else employee.first_name}")
print(f"Initial AL Balance: Used: {balance.used_days}, Remaining: {balance.remaining_days}")

from decimal import Decimal

# Create a pending leave request
start_date = date.today() + timedelta(days=1)
end_date = start_date # 1 day

leave_req = LeaveRequest.objects.create(
    employee=employee,
    leave_type=al_type,
    start_date=start_date,
    end_date=end_date,
    total_days=Decimal('1.00'),
    salary_deduction_days=Decimal('0.00'),
    status='Pending',
    reason='Test AL deduction'
)
print(f"Created Leave Request ID {leave_req.id}, Status: {leave_req.status}")

# Simulate approve logic exactly as in views.py
paid_days = leave_req.total_days - leave_req.salary_deduction_days

if balance.remaining_days >= paid_days:
    balance.used_days += paid_days
    balance.remaining_days -= paid_days
    balance.save()
    leave_req.status = 'Approved'
    leave_req.save()
    print(f"Approved Leave Request. Paid days deducted: {paid_days}")
else:
    print("Insufficient balance.")

# Fetch balance again
balance.refresh_from_db()
print(f"Final AL Balance: Used: {balance.used_days}, Remaining: {balance.remaining_days}")

# Cleanup
leave_req.delete()
balance.used_days -= paid_days
balance.remaining_days += paid_days
balance.save()
print("Cleaned up test data.")

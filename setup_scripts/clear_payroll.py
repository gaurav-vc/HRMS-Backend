import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import SalaryComponent, Loan, Reimbursement, PayrollRun

PayrollRun.objects.all().delete()
Loan.objects.all().delete()
Reimbursement.objects.all().delete()
SalaryComponent.objects.all().delete()

print("All dummy payroll data has been deleted from the database!")

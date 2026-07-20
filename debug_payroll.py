import os
import django
import sys
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.db.models import Sum
from payroll.models import PayrollRun, Payslip

run = PayrollRun.objects.order_by('-period').first()
if not run:
    print("No payroll run found.")
else:
    slips = run.payslip_set.all()
    
    gross_sum = slips.aggregate(Sum('gross'))['gross__sum']
    net_sum = slips.aggregate(Sum('net'))['net__sum']
    
    # Also calculate the sum of negative pay adjustments
    lines_adj = Payslip.objects.filter(run=run, lines__rule__name="Negative Pay Adjustment").aggregate(Sum("lines__amount"))['lines__amount__sum']

    print(f"Period: {run.period}")
    print(f"Total Employees: {slips.count()}")
    print(f"Gross DB sum: {gross_sum}")
    print(f"Net DB sum: {net_sum}")
    print(f"Negative Pay Adjustment: {lines_adj}")

    # Create a small report file
    with open('payroll_debug_report.txt', 'w') as f:
        f.write(f"Period: {run.period}\n")
        f.write(f"Employees: {slips.count()}\n")
        f.write(f"Gross: {gross_sum}\n")
        f.write(f"Net: {net_sum}\n")
        f.write(f"Negative Adjustments: {lines_adj}\n")
        
    print("\nSaved report to payroll_debug_report.txt")

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import PayrollRun, Payslip, SimulatedPayslip, PayrollEvent, PayrollException, StatutoryRegister

def remove_payroll():
    print("Starting payroll cleanup...")
    
    # Delete Payroll Runs (this will cascade to Payslips, SimulatedPayslips, Exceptions, Registers, etc.)
    runs_deleted, _ = PayrollRun.objects.all().delete()
    print(f"Deleted {runs_deleted} PayrollRuns.")

    # Explicitly clear other loose ends if any
    payslips_deleted, _ = Payslip.objects.all().delete()
    print(f"Deleted {payslips_deleted} orphaned Payslips.")

    sim_payslips_deleted, _ = SimulatedPayslip.objects.all().delete()
    print(f"Deleted {sim_payslips_deleted} SimulatedPayslips.")
    
    events_deleted, _ = PayrollEvent.objects.all().delete()
    print(f"Deleted {events_deleted} PayrollEvents.")

    print("Payroll cleanup completed successfully!")

if __name__ == "__main__":
    remove_payroll()

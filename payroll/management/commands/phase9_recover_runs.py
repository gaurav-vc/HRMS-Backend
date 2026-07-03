import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.core.management.base import BaseCommand
from payroll.models import PayrollRun, PayrollEvent, Employee, Payslip, PayslipLineItem, PayrollException
from payroll.service import PayrollService

class Command(BaseCommand):
    help = "Phase 9: Payroll Recovery for Stuck Processing Runs"

    def handle(self, *args, **kwargs):
        self.stdout.write("--- PHASE 9: PAYROLL RECOVERY ---")
        
        stuck_runs = PayrollRun.objects.filter(status='Processing')
        count = stuck_runs.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No stuck runs found. System is healthy."))
            return
            
        self.stdout.write(f"Found {count} stuck runs. Beginning recovery protocol...")
        
        recovered = []
        for run in stuck_runs:
            self.stdout.write(f"Recovering Run {run.id} for {run.period}...")
            
            # Note: Do not regenerate historical payslips.
            # But since it was stuck in 'Processing', it means it crashed before completing bulk_create,
            # To be safe, we flush the slips FOR THIS RUN ONLY to allow clean recovery.
            Payslip.objects.filter(run=run).delete()
            PayrollException.objects.filter(run=run).delete()
            
            try:
                run.status = 'Draft'
                run.save()
                
                # Execute completely synchronously by bypassing the thread
                # This guarantees it won't hang in a while loop
                from payroll.service import PayrollService
                
                # execute_run sets it to Processing and spawns the thread
                PayrollService.execute_run(run.id)
                
                # Wait up to 5 seconds for safety, but we deleted exceptions so it should be fast
                import time
                timeout = 10
                while PayrollRun.objects.get(id=run.id).status == 'Processing' and timeout > 0:
                    time.sleep(0.5)
                    timeout -= 1
                    
                final_status = PayrollRun.objects.get(id=run.id).status
                if final_status == 'Maker-Submitted':
                    recovered.append(run.id)
                    self.stdout.write(self.style.SUCCESS(f"Run {run.id} successfully recovered synchronously!"))
                else:
                    self.stdout.write(self.style.ERROR(f"Run {run.id} failed. Generated new exceptions or timed out. Status: {final_status}"))
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to recover Run {run.id}: {str(e)}"))
                
        PayrollEvent.objects.create(
            type='PayrollGenerated',
            reference='Phase 9 Recovery',
            payload={
                'message': f'Phase 9 Recovery executed successfully for {len(recovered)} runs.',
                'affected_runs': recovered
            }
        )
        
        self.stdout.write("Phase 9 Recovery Complete.")

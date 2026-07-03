from django.core.management.base import BaseCommand
from payroll.models import PayrollRun
from payroll.service import PayrollService

class Command(BaseCommand):
    help = 'Executes a Draft Payroll Run using the new DAG engine'

    def add_arguments(self, parser):
        parser.add_argument('run_id', type=int, help='The ID of the PayrollRun to execute')

    def handle(self, *args, **options):
        run_id = options['run_id']
        try:
            run = PayrollRun.objects.get(id=run_id)
        except PayrollRun.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'PayrollRun with ID {run_id} does not exist.'))
            return

        self.stdout.write(self.style.NOTICE(f'Starting execution for Run {run.period} (ID: {run.id})...'))
        
        try:
            finished_run = PayrollService.execute_run(run.id)
            if finished_run.status == 'Processing':
                self.stdout.write(self.style.WARNING('Run finished with Exceptions! Please check the HR Exception Queue.'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Successfully completed run {run.period}! Status is now {finished_run.status}.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Engine execution failed: {str(e)}'))

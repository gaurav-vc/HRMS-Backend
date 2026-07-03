from decimal import Decimal
from datetime import datetime
import calendar

from employees.models import Employee, CompensationHistory
from payroll.models import PayrollRun, Payslip, SimulatedPayslip, RetroPayrollEntry
from payroll.engine import build_dag_and_sort
from payroll.service import PayrollService

def detect_and_generate_retros(employee, current_run):
    """
    Detects if there are CompensationHistory records effective before the current_run's period
    that differ from what was actually paid in those past periods.
    """
    try:
        cur_year, cur_month = map(int, current_run.period.split('-'))
        current_run_start_date = datetime(cur_year, cur_month, 1).date()
    except Exception:
        return []
        
    # Get all CompensationHistory records that were effective before this run
    # and were created recently (we could filter by created_at > last_run_date)
    # For now, we'll just evaluate all past Frozen payslips and compare them.
    
    frozen_slips = Payslip.objects.filter(employee=employee, run__status__in=['Frozen', 'Disbursed'])
    
    generated_retros = []
    
    for slip in frozen_slips:
        # What was the period of this slip?
        try:
            s_year, s_month = map(int, slip.period.split('-'))
            slip_start_date = datetime(s_year, s_month, 1).date()
            last_day = calendar.monthrange(s_year, s_month)[1]
            slip_end_date = datetime(s_year, s_month, last_day).date()
        except Exception:
            continue
            
        # Is there a CompensationHistory for this employee active during this slip's period?
        # A history is active if effective_from <= slip_end_date and (effective_to >= slip_start_date or effective_to is null)
        active_history = CompensationHistory.objects.filter(
            employee=employee,
            effective_from__lte=slip_end_date
        ).exclude(
            effective_to__lt=slip_start_date
        ).order_by('-effective_from').first()
        
        if not active_history:
            continue
            
        # Optimization: if the history was already processed, skip it.
        # But how do we know? We can just simulate it and see if there's a diff.
        
        # Simulate the payroll for this past run using the new CTC and Structure
        # We temporarily mock the employee's CTC and structure
        original_ctc = employee.ctc
        original_struct = employee.salary_structure
        
        employee.ctc = active_history.ctc
        employee.salary_structure = active_history.salary_structure
        
        # We need the precomputed context for that past run!
        precomputed_data = PayrollService._precompute_payroll_data(slip.run)
        
        # Build DAG
        rules = list(employee.salary_structure.components.all())
        employee._cached_dag = build_dag_and_sort(rules)
        
        try:
            gross, ded, net, lines = PayrollService.process_employee_in_memory(employee, slip.run, precomputed_data, is_simulation=True)
            
            diff_net = net - slip.net
            
            if diff_net > 0:
                # Arrears! Check if a retro already exists for this slip and target run
                exists = RetroPayrollEntry.objects.filter(
                    original_payslip=slip,
                    target_run=current_run
                ).exists()
                
                if not exists:
                    retro = RetroPayrollEntry.objects.create(
                        original_payslip=slip,
                        target_run=current_run,
                        diff_amount=diff_net,
                        approved_for_merge=True # Auto-approve for demo purposes
                    )
                    generated_retros.append(retro)
        finally:
            # Restore
            employee.ctc = original_ctc
            employee.salary_structure = original_struct
            
    return generated_retros

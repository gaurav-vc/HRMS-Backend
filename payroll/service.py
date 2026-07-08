from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from employees.models import Employee
from .models import (
    PayrollRun, Payslip, PayslipLineItem, SimulatedPayslip, SimulatedLineItem,
    PayrollException, ComponentRule, PayrollSettings, PayslipAllocationSnapshot
)
from .engine import build_dag_and_sort, evaluate_component, calculate_tds

class LockService:
    @staticmethod
    def is_locked(employee, date):
        """
        Central lock authority.
        Returns True if the date falls within or before a locked PayrollRun's cutoff
        for this employee's entity/cost center.
        """
        # A simple implementation: find any PayrollRun for the employee's entity
        # that has a lock_date >= the target date, and status NOT in Draft/Processing
        runs = PayrollRun.objects.filter(
            entity=employee.department.entity, # Assuming Employee -> Department -> Entity
            lock_date__gte=date
        ).exclude(status__in=['Draft', 'Processing'])
        
        return runs.exists()

class PayrollService:
    @staticmethod
    def _precompute_payroll_data(run):
        from datetime import datetime
        import calendar
        from attendance.models import DailyAttendance
        from leaves.models import LeaveRequest, Holiday
        from django.db.models import Sum, Count, Q
        
        try:
            year, month = map(int, run.period.split('-'))
            start_date = datetime(year, month, 1).date()
            last_day = calendar.monthrange(year, month)[1]
            end_date = datetime(year, month, last_day).date()
        except Exception:
            return {}, 22
            
        # 1. Total Days
        total_days = last_day
        
        # 2. Weekends & Holidays (Globally for the entity)
        weekends = sum(1 for d in range(1, last_day + 1) if calendar.weekday(year, month, d) >= 5)
        holidays = Holiday.objects.filter(date__range=[start_date, end_date]).count()
        free_paid_days = weekends + holidays
        
        # 3. Pre-aggregate attendance (Punches)
        attendance_qs = DailyAttendance.objects.filter(
            employee__entity=run.entity,
            attendance_date__range=[start_date, end_date]
        ).values('employee_id').annotate(
            present_count=Count('id', filter=Q(attendance_status__in=['Present', 'Late'])),
            late_count=Count('id', filter=Q(attendance_status='Late')),
            half_day_count=Count('id', filter=Q(attendance_status='Half Day')),
            absent_count=Count('id', filter=Q(attendance_status='Absent')),
            total_overtime=Sum('overtime_hours')
        )
        att_map = {item['employee_id']: item for item in attendance_qs}
        
        # 4. Pre-aggregate Paid Leaves
        leaves_qs = LeaveRequest.objects.filter(
            employee__entity=run.entity,
            status='Approved',
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        
        leave_map = {}
        lop_map = {}
        for leave in leaves_qs:
            # Calculate overlap with current month
            o_start = max(leave.start_date, start_date)
            o_end = min(leave.end_date, end_date)
            days = (o_end - o_start).days + 1
            if days > 0:
                if 'loss of pay' in (leave.leave_type.name or '').lower() or 'lop' in (leave.leave_type.name or '').lower() or leave.sub_type == 'LOP':
                    lop_map[leave.employee_id] = lop_map.get(leave.employee_id, 0) + days
                else:
                    leave_map[leave.employee_id] = leave_map.get(leave.employee_id, 0) + days
                
        # 5. Pre-aggregate YTD Gross and TDS for TDS calculation
        financial_year_start = f"{year}-04" if month >= 4 else f"{year-1}-04"
        ytd_qs = Payslip.objects.filter(
            employee__entity=run.entity,
            period__gte=financial_year_start,
            period__lt=run.period
        ).values('employee_id').annotate(
            ytd_gross=Sum('gross'),
            ytd_tds=Sum('lines__amount', filter=Q(lines__rule__name__icontains='TDS'))
        )
        ytd_map = {item['employee_id']: item for item in ytd_qs}

        return {
            'total_days': total_days,
            'free_paid_days': free_paid_days,
            'att_map': att_map,
            'leave_map': leave_map,
            'lop_map': lop_map,
            'ytd_map': ytd_map,
            'month': month
        }

    @staticmethod
    def _get_context_for_employee(employee, precomputed_data):
        settings = PayrollSettings.objects.first() or PayrollSettings()
        
        total_days = precomputed_data.get('total_days', 30)
        free_paid_days = precomputed_data.get('free_paid_days', 8)
        
        emp_att = precomputed_data.get('att_map', {}).get(employee.id, {})
        present_count = emp_att.get('present_count', 0)
        late_count = emp_att.get('late_count', 0)
        half_day_count = emp_att.get('half_day_count', 0)
        absent_count = emp_att.get('absent_count', 0)
        overtime_hours = emp_att.get('total_overtime', Decimal('0.00')) or Decimal('0.00')
        
        paid_leave_days = precomputed_data.get('leave_map', {}).get(employee.id, 0)
        lop_days = precomputed_data.get('lop_map', {}).get(employee.id, 0)
        
        # Late coming penalty: For every 3 days late, cut 0.5 days of salary
        late_penalty_days = (late_count // 3) * 0.5
        
        # Dynamic Punch-Driven Model (Deduction Based)
        # We start with the full month (total_days) and explicitly deduct infractions.
        worked_days = float(present_count) + (float(half_day_count) * 0.5)
        
        if worked_days == 0 and paid_leave_days == 0 and absent_count > 0:
            # If they didn't work at all and have no paid leaves, they get 0 (unless they are new joined with no punches yet)
            calculated_paid_days = 0.0
        else:
            calculated_paid_days = float(total_days) - float(absent_count) - (float(half_day_count) * 0.5) - float(lop_days) - float(late_penalty_days)
            
        present_days = max(0.0, min(calculated_paid_days, float(total_days)))
        
        return {
            'ctc': Decimal(employee.ctc or 0),
            'monthly_ctc': Decimal(employee.ctc or 0) / Decimal(12),
            'present_days': Decimal(str(present_days)),
            'actual_present_days': Decimal(str(worked_days)),
            'total_days': Decimal(str(total_days)),
            'overtime_hours': Decimal(str(overtime_hours)),
            'absent_days': Decimal(str(absent_count)),
            'lop_days': Decimal(str(lop_days)),
            'paid_days': Decimal(str(present_days)),
            'pf_wage_limit': settings.pf_wage_limit,
            'esic_wage_limit': settings.esic_wage_limit,
            'state': 'KA', 
            'current_month': precomputed_data.get('month', 1),
            'gender': getattr(employee, 'gender', 'Male'),
        }

    @staticmethod
    def process_employee_in_memory(employee, run, precomputed_data, is_simulation=False, include_variable_bonus=False):
        rules_dag = getattr(employee, '_cached_dag', [])
        context = PayrollService._get_context_for_employee(employee, precomputed_data)
        
        total_gross = Decimal('0.00')
        total_deductions = Decimal('0.00')
        line_items = []
        
        # Inject defaults to prevent engine crashes if components are completely deleted
        context['basic'] = Decimal('0.00')
        context['hra'] = Decimal('0.00')
        context['non_balancing_gross'] = Decimal('0.00')
        
        # Inject Enterprise OT Engine Parameters
        context['ot_hours'] = context.get('overtime_hours', Decimal('0.00')) 
        # For now, default multiplier is 1.5. A more advanced engine would fetch this from ShiftDefinition.
        context['ot_multiplier'] = Decimal('1.50') 
        
        for rule in rules_dag:
            # PF Applicability Filter
            if rule.name == 'Provident Fund' and not getattr(employee, 'pf_applicable', False):
                continue
                
            if context.get('present_days', Decimal('1')) == Decimal('0'):
                val = Decimal('0.00')
            elif rule.is_statutory and ('TDS' in rule.name.upper() or 'INCOME TAX' in rule.name.upper()):
                ytd_data = precomputed_data.get('ytd_map', {}).get(employee.id, {})
                ytd_gross = ytd_data.get('ytd_gross') or Decimal('0.00')
                ytd_tax_paid = ytd_data.get('ytd_tds') or Decimal('0.00')
                remaining_months = max(1, 12 - precomputed_data.get('month', 1))
                
                emp_regime = getattr(employee, 'tax_regime', 'New')
                emp_deductions = Decimal(str(getattr(employee, 'tax_saving_deductions', '0.00')))
                
                val = calculate_tds(ytd_gross, ytd_tax_paid, total_gross, remaining_months, regime=emp_regime, gender=context.get('gender', 'Male'), deductions=emp_deductions)
            else:
                context['non_balancing_gross'] = total_gross
                val = evaluate_component(rule, context)
            
            context[rule.name] = val
            if getattr(rule, 'variable_code', None):
                context[rule.variable_code] = val
                
            # Legacy alias injections (to be retired in Phase 11)
            name_lower = rule.name.lower()
            if 'basic' in name_lower:
                context['basic'] = val
            if 'hra' in name_lower:
                context['hra'] = val
            
            if rule.type == 'Earning':
                total_gross += val
            elif rule.type == 'Deduction':
                total_deductions += val
            elif rule.type == 'Employer Contribution':
                pass 
                
            line_items.append({'rule': rule, 'amount': val})
            
        # ==========================================
        # RETRO ARREARS INJECTION
        # ==========================================
        from payroll.models import RetroPayrollEntry, ComponentRule
        
        total_arrears = Decimal('0.00')
        if run and run.pk:
            retros = RetroPayrollEntry.objects.filter(
                original_payslip__employee=employee,
                target_run=run,
                approved_for_merge=True
            )
            total_arrears = sum(r.diff_amount for r in retros)
        
        if total_arrears > 0:
            total_gross += total_arrears
            
            # Create a virtual ComponentRule reference for the LineItem
            virtual_rule, _ = ComponentRule.objects.get_or_create(
                name="Retroactive Arrears",
                type="Earning",
                defaults={
                    'formula': "0",
                    'effective_from': "2020-01-01"
                }
            )
            line_items.append({'rule': virtual_rule, 'amount': total_arrears})
            
        # ==========================================
        # VARIABLE BONUS INJECTION
        # ==========================================
        if include_variable_bonus and getattr(employee, 'bonus_applicable', False):
            bonus_amount = Decimal('0.00')
            bonus_type = getattr(employee, 'bonus_type', None)
            bonus_val = Decimal(str(getattr(employee, 'bonus_value', '0.00') or '0.00'))
            emp_ctc = Decimal(str(employee.ctc or 0))
            
            if bonus_type == 'Fixed Amount':
                bonus_amount = bonus_val
            elif bonus_type == 'Percentage':
                bonus_amount = (emp_ctc * bonus_val) / Decimal('100.0')
            elif bonus_type == 'Monthly Salary':
                months_multiplier = Decimal(str(getattr(employee, 'bonus_months', 1) or 1))
                bonus_amount = (emp_ctc / Decimal('12.0')) * months_multiplier
                
            if bonus_amount > emp_ctc:
                raise ValueError(f"CRITICAL ERROR: Calculated Variable Bonus ({bonus_amount}) exceeds the Total CTC ({emp_ctc}) for employee {employee.code}. Execution halted to prevent miscalculation.")
                
            if bonus_amount > 0:
                total_gross += bonus_amount
                virtual_bonus_rule, _ = ComponentRule.objects.get_or_create(
                    name="Variable Bonus",
                    type="Earning",
                    defaults={'formula': "0", 'effective_from': "2020-01-01"}
                )
                line_items.append({'rule': virtual_bonus_rule, 'amount': round(bonus_amount, 2)})
            
        net = total_gross - total_deductions
        if net < 0:
            raise ValueError(f"Negative net pay generated: {net}")
            
        return total_gross, total_deductions, net, line_items

    @staticmethod
    def _run_async_worker(run_id, is_simulation, overrides=None, include_variable_bonus=False):
        # We use a raw thread here strictly because Celery is not installed in the environment.
        # In a real enterprise setup (Wave 7), this MUST be a celery @shared_task.
        import threading
        
        def worker():
            from django.db import connection
            try:
                run = PayrollRun.objects.get(id=run_id)
                if is_simulation:
                    SimulatedPayslip.objects.filter(run=run).delete()
                    employees = Employee.objects.filter(entity=run.entity, status='Active')
                else:
                    employees = Employee.objects.filter(entity=run.entity, status='Active').exclude(
                        payslip__run=run
                    )
                    
                # PREFETCH to kill N+1 queries
                employees = employees.select_related('salary_structure').prefetch_related(
                    'salary_structure__components', 
                    'allocations', 
                    'allocations__cost_center'
                )
                
                # PRECOMPUTE aggregations to kill N+1 queries
                precomputed_data = PayrollService._precompute_payroll_data(run)
                
                # Cache DAGs to avoid rebuilding for identical structures
                dag_cache = {}
                for emp in employees:
                    struct = emp.salary_structure
                    if struct:
                        if struct.id not in dag_cache:
                            emp_rules = list(struct.components.all())
                            dag_cache[struct.id] = build_dag_and_sort(emp_rules) if emp_rules else []
                        emp._cached_dag = dag_cache[struct.id]
                    else:
                        emp._cached_dag = []
                
                slips_to_create = []
                slip_lines_data = []
                allocations_data = []
                exceptions = []
                
                # O(1) Loop
                for emp in employees:
                    try:
                        if not emp.salary_structure:
                            raise ValueError(f"Employee {emp.code} has no Salary Structure assigned.")
                        if not getattr(emp, '_cached_dag', []):
                            raise ValueError(f"Assigned structure '{emp.salary_structure.name}' has no components.")
                            
                        gross, ded, net, line_items = PayrollService.process_employee_in_memory(
                            emp, run, precomputed_data, is_simulation, include_variable_bonus
                        )
                        
                        if overrides:
                            emp_override = next((o for o in overrides if o.get('id') == emp.id), None)
                            if emp_override:
                                from decimal import Decimal
                                gross = Decimal(str(emp_override.get('totalAmount', gross)))
                                ded = Decimal(str(emp_override.get('deduction', ded)))
                                net = Decimal(str(emp_override.get('payableSalary', net)))
                                for item in line_items:
                                    rule_name = getattr(item['rule'], 'name', '').upper()
                                    if 'PF' in rule_name:
                                        item['amount'] = Decimal(str(emp_override.get('pf', item['amount'])))
                                    elif 'PT' in rule_name or 'PROFESSIONAL TAX' in rule_name:
                                        item['amount'] = Decimal(str(emp_override.get('pt', item['amount'])))
                                    elif 'REIMBURSEMENT' in rule_name:
                                        item['amount'] = Decimal(str(emp_override.get('reimbursement', item['amount'])))
                                    elif 'INCENTIVE' in rule_name or 'BONUS' in rule_name:
                                        item['amount'] = Decimal(str(emp_override.get('incentive', item['amount'])))
                        
                        if is_simulation:
                            slip = SimulatedPayslip(employee=emp, run=run, period=run.period, gross=gross, deductions=ded, net=net)
                        else:
                            slip = Payslip(employee=emp, run=run, period=run.period, gross=gross, deductions=ded, net=net)
                            
                        slips_to_create.append(slip)
                        slip_lines_data.append(line_items)
                        allocations_data.append(list(emp.allocations.all()))
                        
                    except Exception as e:
                        if not is_simulation:
                            exceptions.append(PayrollException(run=run, employee=emp, error_trace=str(e), resolved=False))
                
                # BATCH INSERTS
                if is_simulation:
                    created_slips = SimulatedPayslip.objects.bulk_create(slips_to_create, batch_size=5000)
                    line_objects = []
                    for slip, lines in zip(created_slips, slip_lines_data):
                        line_objects.extend([SimulatedLineItem(payslip=slip, rule=item['rule'], amount=item['amount']) for item in lines])
                    SimulatedLineItem.objects.bulk_create(line_objects, batch_size=5000)
                else:
                    created_slips = Payslip.objects.bulk_create(slips_to_create, batch_size=5000)
                    line_objects = []
                    alloc_objects = []
                    for slip, lines, allocs in zip(created_slips, slip_lines_data, allocations_data):
                        line_objects.extend([PayslipLineItem(payslip=slip, rule=item['rule'], amount=item['amount']) for item in lines])
                        alloc_objects.extend([PayslipAllocationSnapshot(payslip=slip, cost_center=a.cost_center, percentage=a.percentage) for a in allocs])
                    PayslipLineItem.objects.bulk_create(line_objects, batch_size=5000)
                    PayslipAllocationSnapshot.objects.bulk_create(alloc_objects, batch_size=5000)
                    if exceptions:
                        PayrollException.objects.bulk_create(exceptions, batch_size=5000)
                
                if not is_simulation:
                    # Resolve fixed exceptions
                    successful_emp_ids = [s.employee_id for s in slips_to_create]
                    PayrollException.objects.filter(run=run, employee_id__in=successful_emp_ids).update(resolved=True)
                            
                has_exceptions = PayrollException.objects.filter(run=run, resolved=False).exists()
                if has_exceptions:
                    run.status = 'Processing'
                else:
                    run.status = 'Maker-Submitted'
                    # Notify Approvers
                    from employees.models import Notification
                    for approver in Employee.objects.filter(status='Active'):
                        if approver.dynamic_role and approver.dynamic_role.permissions and approver.dynamic_role.permissions.get('can_approve_payroll'):
                            Notification.objects.create(
                                recipient=approver,
                                title="Payroll Ready for Review",
                                message=f"Payroll for {run.period} has been processed and is awaiting your approval.",
                                related_run_id=run.id
                            )
                run.save()
            finally:
                connection.close()
                
        if is_simulation:
            thread = threading.Thread(target=worker)
            thread.daemon = True
            thread.start()
        else:
            # Run synchronously so it completes before the API returns
            worker()

    @staticmethod
    def execute_run(run_id, overrides=None, include_variable_bonus=False):
        run = PayrollRun.objects.get(id=run_id)
        if run.status != 'Draft':
            raise ValueError("Can only execute Draft runs")
        run.status = 'Processing'
        run.save()
        is_simulation = (run.run_type == 'Simulation')
        PayrollService._run_async_worker(run_id, is_simulation, overrides=overrides, include_variable_bonus=include_variable_bonus)
        run.refresh_from_db()
        return run

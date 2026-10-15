import decimal
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from employees.models import Employee
from .models import (
    PayrollRun, Payslip, PayslipLineItem, SimulatedPayslip, SimulatedLineItem,
    PayrollException, ComponentRule, PayrollSettings, PayslipAllocationSnapshot,
    Reimbursement
)
from .engine import build_dag_and_sort, evaluate_component, calculate_tds

class LockService:
    @staticmethod
    def get_employee_entity(employee):
        if not employee:
            return None
        if getattr(employee, 'entity', None):
            return employee.entity
        if getattr(employee, 'site', None) and getattr(employee.site, 'branch', None) and getattr(employee.site.branch, 'entity', None):
            return employee.site.branch.entity
        if getattr(employee, 'department', None) and getattr(employee.department, 'entity', None):
            return getattr(employee.department, 'entity', None)
        return None

    @staticmethod
    def is_locked(employee, date):
        """
        Central lock authority.
        Returns True if the date falls within or before a locked PayrollRun's cutoff
        for this employee's entity/cost center, or within a finalized payroll period.
        """
        if not employee or not date:
            return False

        import datetime
        target_date = date.date() if isinstance(date, datetime.datetime) else date

        emp_entity = LockService.get_employee_entity(employee)
        if not emp_entity:
            return False

        # Runs that are locked or finalized (not Draft or Processing) strictly for this employee's entity
        runs = PayrollRun.objects.filter(entity=emp_entity).exclude(status__in=['Draft', 'Processing'])

        # 1. Lock check by lock_date cutoff
        if runs.filter(lock_date__isnull=False, lock_date__gte=target_date).exists():
            return True

        # 2. Lock check by payroll period (YYYY-MM)
        period_str = target_date.strftime('%Y-%m')
        if runs.filter(period=period_str).exists():
            return True

        return False

    @staticmethod
    def is_attendance_locked(attendance):
        """
        Returns True if the daily attendance record is locked:
        1. Either the employee & attendance_date fall in a locked/finalized payroll run,
        2. Or it is linked to an Overtime Request that was already finalized/disbursed in payroll.
        """
        if not attendance or not attendance.employee or not attendance.attendance_date:
            return False

        if LockService.is_locked(attendance.employee, attendance.attendance_date):
            return True

        # Check if attendance is linked to an OT entry processed in a finalized payroll run
        try:
            from ot_engine.models import OTPayrollEntry
            if OTPayrollEntry.objects.filter(
                ot_entry__request__attendance=attendance
            ).exclude(payroll_run__status__in=['Draft', 'Processing']).exists():
                return True
        except Exception:
            pass

        return False

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
        emp_filter = Q(employee__entity=run.entity) | Q(employee__branch__entity=run.entity) | Q(employee__site__branch__entity=run.entity)
        attendance_qs = DailyAttendance.objects.filter(
            emp_filter,
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
            emp_filter,
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
            emp_filter,
            period__gte=financial_year_start,
            period__lt=run.period
        ).values('employee_id').annotate(
            ytd_gross=Sum('gross'),
            ytd_tds=Sum('lines__amount', filter=Q(lines__rule__name__icontains='TDS'))
        )
        ytd_map = {item['employee_id']: item for item in ytd_qs}

        # 6. Pre-aggregate Approved Reimbursements
        reimb_qs = Reimbursement.objects.filter(
            emp_filter,
            status='Approved'
        ).values('employee_id').annotate(total_reimb=Sum('amount'))
        reimb_map = {item['employee_id']: item['total_reimb'] for item in reimb_qs}

        return {
            'total_days': total_days,
            'free_paid_days': free_paid_days,
            'att_map': att_map,
            'leave_map': leave_map,
            'lop_map': lop_map,
            'ytd_map': ytd_map,
            'reimb_map': reimb_map,
            'month': month
        }

    @staticmethod
    def _get_context_for_employee(employee, precomputed_data, emp_override=None):
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
        
        late_penalty_days = (late_count // 3) * 0.5
        
        # Override attendance variables if provided (check both camel/snake case due to DRF middleware)
        if emp_override:
            if 'leaves' in emp_override: paid_leave_days = float(emp_override['leaves'] or 0)
            elif 'paid_leave_days' in emp_override: paid_leave_days = float(emp_override['paid_leave_days'] or 0)
            elif 'annual_leaves' in emp_override: paid_leave_days = float(emp_override['annual_leaves'] or 0)
            elif 'annualLeaves' in emp_override: paid_leave_days = float(emp_override['annualLeaves'] or 0)

            if 'lop_days' in emp_override: lop_days = float(emp_override['lop_days'] or 0)
            elif 'lopDays' in emp_override: lop_days = float(emp_override['lopDays'] or 0)
            elif 'lop' in emp_override: lop_days = float(emp_override['lop'] or 0)
            
            if 'half_days' in emp_override: half_day_count = float(emp_override['half_days'] or 0)
            elif 'halfDays' in emp_override: half_day_count = float(emp_override['halfDays'] or 0)
            
            if 'late_penalties' in emp_override: late_penalty_days = float(emp_override['late_penalties'] or 0)
            elif 'latePenalties' in emp_override: late_penalty_days = float(emp_override['latePenalties'] or 0)
            
            if 'ot' in emp_override: overtime_hours = Decimal(str(emp_override['ot'] or 0))
            elif 'ot_hours' in emp_override: overtime_hours = Decimal(str(emp_override['ot_hours'] or 0))
            elif 'overtimeHours' in emp_override: overtime_hours = Decimal(str(emp_override['overtimeHours'] or 0))
            elif 'overtime' in emp_override: overtime_hours = Decimal(str(emp_override['overtime'] or 0))

            if 'present_days' in emp_override: present_count = float(emp_override['present_days'] or 0)
            elif 'presentDays' in emp_override: present_count = float(emp_override['presentDays'] or 0)
        
        worked_days = float(present_count) + (float(half_day_count) * 0.5)
        
        if worked_days == 0 and paid_leave_days == 0 and not emp_override:
            calculated_paid_days = 0.0
        else:
            calculated_paid_days = float(total_days) - float(absent_count) - (float(half_day_count) * 0.5) - float(lop_days) - float(late_penalty_days)
            
        # Determine payable days with 100% mathematical precision
        calculated_override_payable = max(0.0, float(total_days) - float(lop_days) - (float(half_day_count) * 0.5) - float(late_penalty_days))
        calculated_override_payable = min(calculated_override_payable, float(total_days))

        if emp_override:
            user_days_paid = None
            for key in ['daysPaid', 'days_paid', 'payable_days', 'payableDays']:
                if key in emp_override and emp_override[key] is not None and str(emp_override[key]).strip() != '':
                    try:
                        user_days_paid = float(emp_override[key])
                        break
                    except (ValueError, TypeError):
                        pass

            has_explicit_deduction_override = any(
                k in emp_override and emp_override[k] is not None and str(emp_override[k]).strip() != ''
                for k in ['lop_days', 'lopDays', 'lop', 'half_days', 'halfDays', 'late_penalties', 'latePenalties']
            )

            if has_explicit_deduction_override:
                if user_days_paid is not None and user_days_paid < calculated_override_payable:
                    present_days = user_days_paid
                else:
                    present_days = calculated_override_payable
            elif user_days_paid is not None:
                present_days = max(0.0, min(user_days_paid, float(total_days)))
            elif 'present_days' in emp_override or 'presentDays' in emp_override:
                present_days = max(0.0, min(float(emp_override.get('present_days') or emp_override.get('presentDays') or 0), float(total_days)))
            else:
                present_days = max(0.0, min(calculated_paid_days, float(total_days)))
        else:
            present_days = max(0.0, min(calculated_paid_days, float(total_days)))
        
        reimbursement_amount = precomputed_data.get('reimb_map', {}).get(employee.id, Decimal('0.00'))
        if not reimbursement_amount:
            reimbursement_amount = Decimal('0.00')
        
        return {
            'ctc': Decimal(employee.ctc or 0),
            'monthly_ctc': Decimal(employee.ctc or 0) / Decimal(12),
            'present_days': Decimal(str(present_days)),
            'actual_present_days': Decimal(str(worked_days)),
            'total_days': Decimal(str(total_days)),
            'overtime_hours': Decimal(str(overtime_hours)),
            'ot_hours': Decimal(str(overtime_hours)),
            'absent_days': Decimal(str(absent_count)),
            'lop_days': Decimal(str(lop_days)),
            'half_day_count': Decimal(str(half_day_count)),
            'late_penalty_days': Decimal(str(late_penalty_days)),
            'paid_days': Decimal(str(present_days)),
            'paid_leave_days': Decimal(str(paid_leave_days)),
            'annual_leaves': Decimal(str(paid_leave_days)),
            'pf_wage_limit': settings.pf_wage_limit,
            'esic_wage_limit': settings.esic_wage_limit,
            'state': 'KA', 
            'current_month': precomputed_data.get('month', 1),
            'gender': getattr(employee, 'gender', 'Male'),
            'reimbursement': Decimal(str(reimbursement_amount)),
        }

    @staticmethod
    def process_employee_in_memory(employee, run, precomputed_data, is_simulation=False, include_variable_bonus=False, emp_override=None, include_leaves_encashment=False):
        rules_dag = getattr(employee, '_cached_dag', [])
        context = PayrollService._get_context_for_employee(employee, precomputed_data, emp_override=emp_override)
        
        total_gross = Decimal('0.00')
        total_deductions = Decimal('0.00')
        line_items = []
        
        # Inject defaults to prevent engine crashes if components are completely deleted
        context['basic'] = Decimal('0.00')
        context['hra'] = Decimal('0.00')
        context['non_balancing_gross'] = Decimal('0.00')
        
        # Inject Enterprise OT Engine Parameters
        context['ot_hours'] = context.get('overtime_hours', Decimal('0.00')) 
        try:
            from ot_engine.models import OTPolicy
            active_ot_policy = OTPolicy.objects.order_by('-effective_from').first()
            context['ot_multiplier'] = active_ot_policy.multiplier if active_ot_policy else Decimal('1.50')
        except Exception:
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
        
        if emp_override and 'arrears' in emp_override:
            total_arrears = Decimal(str(emp_override['arrears'] or 0))
        elif run:
            if run.pk:
                retros = RetroPayrollEntry.objects.filter(
                    original_payslip__employee=employee,
                    target_run=run,
                    approved_for_merge=True
                )
            else:
                retros = RetroPayrollEntry.objects.filter(
                    original_payslip__employee=employee,
                    target_run__period=run.period,
                    target_run__entity=run.entity,
                    approved_for_merge=True
                )
            total_arrears = sum(r.diff_amount for r in retros)
        
        if total_arrears != 0:
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
            
        # ==========================================
        # AUTOMATED REIMBURSEMENT INJECTION
        # ==========================================
        reimbursement_amt = context.get('reimbursement', Decimal('0.00'))
        if reimbursement_amt > 0:
            found_reimb = False
            for item in line_items:
                if 'REIMBURSEMENT' in getattr(item['rule'], 'name', '').upper():
                    diff = reimbursement_amt - item['amount']
                    if diff != 0:
                        total_gross += diff
                        item['amount'] = reimbursement_amt
                    found_reimb = True
                    break
                    
            if not found_reimb:
                total_gross += reimbursement_amt
                virtual_reimb_rule, _ = ComponentRule.objects.get_or_create(
                    name="Reimbursement", 
                    defaults={'type': 'Earning', 'formula': 'reimbursement', 'is_statutory': False, 'effective_from': timezone.now().date()}
                )
                line_items.append({'rule': virtual_reimb_rule, 'amount': reimbursement_amt})

        # ==========================================
        # OVERTIME (OT) PAY INJECTION
        # ==========================================
        ot_hours = context.get('ot_hours', Decimal('0.00')) or Decimal('0.00')
        if ot_hours > 0:
            # Check if an existing component rule already handled Overtime
            already_handled = any(
                ('OVERTIME' in getattr(item['rule'], 'name', '').upper() or
                 getattr(item['rule'], 'variable_code', '') in ['OT', 'OVERTIME', 'OT_PAY'] or
                 'ot_hours' in (getattr(item['rule'], 'formula', '') or ''))
                for item in line_items
            )
            if not already_handled:
                total_days = context.get('total_days', Decimal('30.00'))
                if total_days <= 0:
                    total_days = Decimal('30.00')
                basic_amt = context.get('basic', Decimal('0.00'))
                if basic_amt <= 0:
                    emp_ctc = Decimal(str(employee.ctc or 0))
                    # Standard labor fallback: 50% of monthly CTC as basic wage if separate basic component not defined
                    basic_amt = (emp_ctc / Decimal('12.0')) * Decimal('0.50') if emp_ctc > 0 else Decimal('0.00')
                
                # Standard hourly rate calculation: (basic_wage / total_days / 8.0)
                hourly_rate = basic_amt / total_days / Decimal('8.00')
                multiplier = context.get('ot_multiplier', Decimal('1.50'))
                ot_pay = (hourly_rate * multiplier * ot_hours).quantize(Decimal('0.01'), rounding=decimal.ROUND_HALF_UP)
                
                if ot_pay > 0:
                    total_gross += ot_pay
                    virtual_ot_rule, _ = ComponentRule.objects.get_or_create(
                        name="Overtime Allowance",
                        defaults={
                            'type': 'Earning',
                            'formula': 'ot_hours * (basic / total_days / 8) * 1.5',
                            'is_statutory': False,
                            'effective_from': timezone.now().date()
                        }
                    )
                    line_items.append({'rule': virtual_ot_rule, 'amount': ot_pay})
                    context['Overtime Allowance'] = ot_pay
                    context['ot_pay'] = ot_pay

        # ==========================================
        # LEAVE ENCASHMENT INJECTION
        # ==========================================
        if include_leaves_encashment:
            from leaves.models import LeaveBalance
            from django.db.models import F
            
            try:
                current_year = int(run.period.split('-')[0])
                balances = LeaveBalance.objects.filter(employee=employee, year=current_year, remaining_days__gt=0)
                
                encashable_leaves = Decimal('0.00')
                balances_to_reset = []
                for bal in balances:
                    name = (bal.leave_type.name or '').upper()
                    if 'ANNUAL' in name or 'EARNED' in name or 'AL' in name:
                        encashable_leaves += bal.remaining_days
                        balances_to_reset.append(bal)
                
                if encashable_leaves > 0:
                    total_days_in_month = context.get('total_days', Decimal('30.00'))
                    if total_days_in_month <= 0:
                        total_days_in_month = Decimal('30.00')
                        
                    daily_rate = context.get('basic', Decimal('0.00')) / Decimal(str(total_days_in_month))
                    if daily_rate <= 0:
                        daily_rate = (Decimal(str(employee.ctc or 0)) / Decimal('12.0')) / Decimal(str(total_days_in_month))
                        
                    encashment_amount = Decimal(str(encashable_leaves)) * daily_rate
                    
                    if encashment_amount > 0:
                        total_gross += encashment_amount
                        virtual_leave_rule, _ = ComponentRule.objects.get_or_create(
                            name="Leave Encashment",
                            defaults={'type': 'Earning', 'formula': '0', 'effective_from': "2020-01-01"}
                        )
                        line_items.append({'rule': virtual_leave_rule, 'amount': round(encashment_amount, 2)})
                        
                        if not is_simulation:
                            for bal in balances_to_reset:
                                bal.used_days = F('used_days') + bal.remaining_days
                                bal.remaining_days = Decimal('0.00')
                                bal.save(update_fields=['used_days', 'remaining_days'])
            except Exception as e:
                import traceback
                print(f"Error processing leave encashment: {e}")
                traceback.print_exc()

        net = total_gross - total_deductions
        if net < 0:
            diff = total_deductions - total_gross
            virtual_adjustment, _ = ComponentRule.objects.get_or_create(
                name="Negative Pay Adjustment",
                type="Earning",
                defaults={'formula': "0", 'effective_from': "2020-01-01"}
            )
            line_items.append({'rule': virtual_adjustment, 'amount': diff})
            total_gross += diff
            net = Decimal('0.00')
            
        return total_gross, total_deductions, net, line_items

    @staticmethod
    def _run_async_worker(run_id, is_simulation, overrides=None, include_variable_bonus=False, include_leaves_encashment=False):
        # We use a raw thread here strictly because Celery is not installed in the environment.
        # In a real enterprise setup (Wave 7), this MUST be a celery @shared_task.
        import threading
        
        def worker():
            from django.db import connection
            try:
                run = PayrollRun.objects.get(id=run_id)
                from django.db.models import Q
                if is_simulation:
                    SimulatedPayslip.objects.filter(run=run).delete()
                    employees = Employee.objects.filter(Q(entity=run.entity) | Q(branch__entity=run.entity) | Q(site__branch__entity=run.entity), status='Active')
                else:
                    employees = Employee.objects.filter(Q(entity=run.entity) | Q(branch__entity=run.entity) | Q(site__branch__entity=run.entity), status='Active').exclude(
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
                from payroll.models import SalaryStructure
                default_struct = SalaryStructure.objects.filter(status='Active').first()
                for emp in employees:
                    struct = (
                        emp.salary_structure or
                        (emp.site and SalaryStructure.objects.filter(site=emp.site, status='Active').first()) or
                        (emp.entity and SalaryStructure.objects.filter(site__branch__entity=emp.entity, status='Active').first()) or
                        default_struct
                    )
                    if struct:
                        emp.salary_structure = struct
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
                            if default_struct:
                                emp.salary_structure = default_struct
                                emp._cached_dag = dag_cache.get(default_struct.id, [])
                            
                        emp_override = None
                        if overrides:
                            emp_override = next((o for o in overrides if o.get('id') == emp.id), None)
                            
                        gross, ded, net, line_items = PayrollService.process_employee_in_memory(
                            emp, run, precomputed_data, is_simulation, include_variable_bonus, emp_override=emp_override, include_leaves_encashment=include_leaves_encashment
                        )
                        
                        if emp_override:
                            from decimal import Decimal
                            # Allow hard overrides of financial amounts if they were edited directly
                            # The engine already recalculated based on attendance, but if user explicitly edited gross/net, honor it
                            if 'totalAmount' in emp_override: gross = Decimal(str(emp_override['totalAmount']))
                            if 'deduction' in emp_override: ded = Decimal(str(emp_override['deduction']))
                            if 'payableSalary' in emp_override: net = Decimal(str(emp_override['payableSalary']))
                            for item in line_items:
                                rule_name = getattr(item['rule'], 'name', '').upper()
                                if 'PF' in rule_name and 'pf' in emp_override:
                                    item['amount'] = Decimal(str(emp_override['pf']))
                                elif ('PT' in rule_name or 'PROFESSIONAL TAX' in rule_name) and 'pt' in emp_override:
                                    item['amount'] = Decimal(str(emp_override['pt']))
                                elif 'REIMBURSEMENT' in rule_name and 'reimbursement' in emp_override:
                                    item['amount'] = Decimal(str(emp_override['reimbursement']))
                                elif ('INCENTIVE' in rule_name or 'BONUS' in rule_name) and 'incentive' in emp_override:
                                    item['amount'] = Decimal(str(emp_override['incentive']))
                                elif ('OVERTIME' in rule_name or 'OT' in rule_name) and ('overtimePay' in emp_override or 'otAmount' in emp_override):
                                    ot_override_amt = emp_override.get('overtimePay') or emp_override.get('otAmount')
                                    item['amount'] = Decimal(str(ot_override_amt))
                        
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
                    run.status = 'Maker-Submitted' # Still submit so approvers can reject/fix
                else:
                    run.status = 'Maker-Submitted'
                    # Notify Approvers
                    from employees.models import Notification
                    for approver in Employee.objects.filter(status='Active'):
                        if approver.dynamic_role and approver.dynamic_role.permissions and approver.dynamic_role.permissions.get('can_approve_payroll') in [True, 'true', 'True', 1, '1']:
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
    def execute_run(run_id, overrides=None, include_variable_bonus=False, include_leaves_encashment=False):
        run = PayrollRun.objects.get(id=run_id)
        if run.status in ['Frozen', 'Disbursed']:
            raise ValueError("Cannot execute a run that is Frozen or Disbursed")

        # Double-check that all active employees in this entity have Salary Structure and CTC
        from employees.models import Employee
        from django.db.models import Q
        active_emps = Employee.objects.filter(
            Q(entity=run.entity) | Q(branch__entity=run.entity) | Q(site__branch__entity=run.entity),
            status='Active'
        ).select_related('salary_structure').prefetch_related('salary_structure__components')
        
        missing_records = []
        for emp in active_emps:
            if not emp.salary_structure or emp.salary_structure.components.count() == 0:
                missing_records.append(f"{emp.code} (Missing Salary Structure)")
            elif not emp.ctc or emp.ctc <= 0:
                missing_records.append(f"{emp.code} (Missing CTC)")
                
        if missing_records:
            raise ValueError(f"Cannot execute payroll. {len(missing_records)} active employee(s) have missing configuration: {', '.join(missing_records[:5])}")

        run.status = 'Processing'
        run.save()
        is_simulation = (run.run_type == 'Simulation')
        PayrollService._run_async_worker(run_id, is_simulation, overrides=overrides, include_variable_bonus=include_variable_bonus, include_leaves_encashment=include_leaves_encashment)
        run.refresh_from_db()
        return run

    @staticmethod
    def file_arrears(run_id, overrides):
        run = PayrollRun.objects.get(id=run_id)
        if not overrides:
            return
            
        precomputed_data = PayrollService._precompute_payroll_data(run)
        
        # Find next active run
        from datetime import datetime
        import calendar
        
        # Calculate exact next period string
        y, m = map(int, run.period.split('-'))
        m += 1
        if m > 12:
            m = 1
            y += 1
        next_period = f"{y}-{m:02d}"
        
        # Find or create the exact next run for this entity
        next_run = PayrollRun.objects.filter(entity=run.entity, period=next_period).first()
        if not next_run:
            next_run, _ = PayrollRun.objects.get_or_create(
                period=next_period,
                entity=run.entity,
                run_type='Live',
                defaults={'status': 'Draft'}
            )
            
        from payroll.models import RetroPayrollEntry
        
        logs = []
        logs.append(f"DEBUG file_arrears: started for run_id={run_id} overrides count: {len(overrides)}")
        for override in overrides:
            emp_id = override.get('id')
            if not emp_id: continue
            logs.append(f"DEBUG file_arrears: processing emp_id={emp_id}, override_presentDays={override.get('presentDays')}")
            try:
                emp = Employee.objects.get(id=emp_id)
                original_slip = Payslip.objects.filter(employee=emp, run=run).first()
                if not original_slip:
                    logs.append(f"DEBUG file_arrears: No original_slip found for emp_id={emp_id} run={run.id}!")
                    continue
                
                logs.append(f"DEBUG file_arrears: Found original_slip net={original_slip.net}")
                
                # Pre-cache DAG
                struct = emp.salary_structure
                if struct:
                    emp._cached_dag = build_dag_and_sort(list(struct.components.all()))
                else:
                    emp._cached_dag = []
                    
                gross, ded, net, line_items = PayrollService.process_employee_in_memory(
                    emp, run, precomputed_data, is_simulation=True, emp_override=override
                )
                
                context = PayrollService._get_context_for_employee(emp, precomputed_data, emp_override=override)
                logs.append(f"DEBUG file_arrears: context present_days={context.get('present_days')}, total_days={context.get('total_days')}")
                
                diff_amount = net - original_slip.net
                logs.append(f"DEBUG file_arrears: Calculated new net={net}, diff_amount={diff_amount}")
                
                if diff_amount != 0:
                    RetroPayrollEntry.objects.update_or_create(
                        original_payslip=original_slip,
                        target_run=next_run,
                        defaults={
                            'diff_amount': diff_amount,
                            'approved_for_merge': True
                        }
                    )
                    logs.append(f"DEBUG file_arrears: Created RetroPayrollEntry for diff={diff_amount}")
                else:
                    logs.append(f"DEBUG file_arrears: Diff is 0, no entry created.")
            except Exception as e:
                import traceback
                logs.append(f"DEBUG file_arrears: Failed to process arrears for {emp_id}: {e}")
                traceback.print_exc()
                pass
                
        return logs

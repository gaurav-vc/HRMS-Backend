from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import PayrollRun, Loan, Reimbursement, ComponentRule, ComplianceReport, SalaryStructure, PayrollException
from .serializers import PayrollRunSerializer, LoanSerializer, ReimbursementSerializer, ComponentRuleSerializer, ComplianceReportSerializer, SalaryStructureSerializer
from employees.models import Employee
from django.utils import timezone

from authentication.permissions import DataIsolationMixin, IsHR
from rest_framework.permissions import IsAuthenticated

class SalaryStructureViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Salary Structure'
    permission_classes = [IsAuthenticated, IsHR]
    queryset = SalaryStructure.objects.all()
    serializer_class = SalaryStructureSerializer

class ComponentRuleViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Salary Structure'
    permission_classes = [IsAuthenticated, IsHR]
    queryset = ComponentRule.objects.all()
    serializer_class = ComponentRuleSerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        structure_id = self.request.query_params.get('structure', None)
        if structure_id is not None:
            qs = qs.filter(structure_id=structure_id)
        return qs

    def destroy(self, request, *args, **kwargs):
        import django.db.models.deletion
        try:
            return super().destroy(request, *args, **kwargs)
        except django.db.models.deletion.ProtectedError:
            return Response(
                {"detail": "Cannot delete this rule because it is linked to past payslips. Please edit the rule and set its value to 0 instead."},
                status=status.HTTP_400_BAD_REQUEST
            )

    def _derive_formula(self, data):
        # Automatically derive formula if not provided or empty
        if 'calc' in data and not data.get('formula'):
            calc = data.get('calc')[0] if isinstance(data.get('calc'), list) else data.get('calc')
            val = data.get('value')[0] if isinstance(data.get('value'), list) else data.get('value', 0)
            
            if calc == 'Fixed':
                data['formula'] = str(val)
            elif calc == '% of Basic':
                data['formula'] = f"basic * ({val} / 100)"
            elif calc == '% of CTC':
                data['formula'] = f"monthly_ctc * ({val} / 100)"
            else:
                data['formula'] = str(val)
        return data

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data = self._derive_formula(data)
                
        # Engine Phase 1: Set effective_from by default if not provided
        if 'effective_from' not in data:
            from django.utils import timezone
            data['effective_from'] = timezone.now().date().isoformat()
            
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=201)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        data = request.data.copy()
        
        data = self._derive_formula(data)
        
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class ComplianceReportViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Compliance'
    queryset = ComplianceReport.objects.all().order_by('due')
    serializer_class = ComplianceReportSerializer

    @action(detail=False, methods=['get'])
    def generate_return(self, request):
        category = request.query_params.get('category')
        if not category:
            return Response({'error': 'Category is required'}, status=400)
            
        pending_reports = self.get_queryset().filter(category=category, status='Pending')
        
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="Compliance_Return_{category.replace(" ", "_")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Category', 'Key', 'Description', 'Period', 'Amount', 'Due Date'])
        
        for report in pending_reports:
            writer.writerow([
                report.category,
                report.key,
                report.desc,
                report.period,
                report.amount,
                report.due.strftime('%Y-%m-%d') if report.due else ''
            ])
            
        return response

from rest_framework.decorators import action
from .service import PayrollService
from authentication.permissions import DataIsolationMixin

def resolve_employee_salary_structure(emp, default_struct=None):
    if emp.salary_structure and emp.salary_structure.components.exists():
        return emp.salary_structure
    from payroll.models import SalaryStructure
    if getattr(emp, 'site', None):
        site_struct = SalaryStructure.objects.filter(site=emp.site, status='Active').first()
        if site_struct and site_struct.components.exists():
            return site_struct
    emp_entity = getattr(emp, 'entity', None)
    if not emp_entity and getattr(emp, 'site', None) and getattr(emp.site, 'branch', None):
        emp_entity = getattr(emp.site.branch, 'entity', None)
    if emp_entity:
        entity_struct = SalaryStructure.objects.filter(site__branch__entity=emp_entity, status='Active').first()
        if entity_struct and entity_struct.components.exists():
            return entity_struct
    if default_struct and default_struct.components.exists():
        return default_struct
    return SalaryStructure.objects.filter(status='Active').first()

class PayrollRunViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Run Payroll'
    queryset = PayrollRun.objects.all().order_by('-period')
    serializer_class = PayrollRunSerializer


    def create(self, request, *args, **kwargs):
        period = request.data.get('period')
        entity_id = request.data.get('entity')
        run_type = request.data.get('run_type', 'Live')
        
        # Prevent multiple runs for the same period and entity
        if period and entity_id:
            existing_run = PayrollRun.objects.filter(period=period, entity_id=entity_id, run_type=run_type).first()
            if existing_run:
                serializer = self.get_serializer(existing_run)
                return Response(serializer.data, status=200)
                
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        user = request.user
        if user.is_superuser:
            return Response({'error': 'Super admin does not have permission to run site payroll.'}, status=403)
        emp = getattr(user, 'employee_profile', None)
        if not emp and user.email:
            from employees.models import Employee
            emp = Employee.objects.filter(email__iexact=user.email).first()

        can_run = False
        if emp and emp.dynamic_role and emp.dynamic_role.permissions:
            perms = emp.dynamic_role.permissions
            if (perms.get('can_run_payroll') in [True, 'true', 'True', 1, '1'] or
                perms.get('can_process_payroll') in [True, 'true', 'True', 1, '1']):
                can_run = True

        if not can_run:
            return Response({'error': 'Permission denied. You do not have permission to run payroll.'}, status=403)

        try:
            run = self.get_object()
            overrides = request.data.get('overrides')
            include_variable_bonus = request.data.get('include_variable_bonus', False)
            include_leaves_encashment = request.data.get('include_leaves_encashment', False)
            
            if run.status in ['Frozen', 'Disbursed']:
                if overrides:
                    PayrollService.file_arrears(run.id, overrides)
                return Response({'status': 'success', 'run_status': run.status, 'msg': 'Arrears processed'})

            # Dynamic resolution of active salary structure for any unassigned employees
            from employees.models import Employee
            from payroll.models import SalaryStructure
            from django.db.models import Q
            active_employees = Employee.objects.filter(
                Q(entity=run.entity) | Q(branch__entity=run.entity) | Q(site__branch__entity=run.entity),
                status='Active'
            ).select_related('salary_structure', 'department', 'designation', 'site', 'entity').prefetch_related('salary_structure__components')

            default_structure = SalaryStructure.objects.filter(status='Active').first()
            for e in active_employees:
                if not e.salary_structure or e.salary_structure.components.count() == 0:
                    struct = resolve_employee_salary_structure(e, default_structure)
                    if struct:
                        e.salary_structure = struct
                        e.save(update_fields=['salary_structure'])
                
            run = PayrollService.execute_run(run.id, overrides=overrides, include_variable_bonus=include_variable_bonus, include_leaves_encashment=include_leaves_encashment)
            if hasattr(request, 'user') and request.user.is_authenticated:
                run.maker = request.user
                run.save()
            
            return Response({'status': 'success', 'run_status': run.status, 'msg': 'Engine started in background'})
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return Response({'status': 'error', 'message': f"CRASH: {str(e)} | Trace: {tb}"}, status=400)

    @action(detail=False, methods=['post', 'get'])
    def validate_prerequisites(self, request):
        """Pre-flight validation check before initiating payroll run"""
        from employees.models import Employee
        from organisation.models import Entity
        from django.db.models import Q
        
        entity_ids = request.data.get('entity_ids') or request.query_params.get('entity_ids')
        if not entity_ids:
            entity_id = request.data.get('entity') or request.query_params.get('entity')
            if entity_id:
                entity_ids = [entity_id]
        
        if entity_ids:
            if isinstance(entity_ids, str):
                entity_ids = [int(x.strip()) for x in entity_ids.split(',') if x.strip().isdigit()]
            entities = Entity.objects.filter(id__in=entity_ids)
        else:
            entities = Entity.objects.all()
            
        from payroll.models import SalaryStructure
        default_structure = SalaryStructure.objects.filter(status='Active').first()
        missing_employees = []
        for entity in entities:
            emps = Employee.objects.filter(
                Q(entity=entity) | Q(branch__entity=entity) | Q(site__branch__entity=entity),
                status='Active'
            ).select_related('salary_structure', 'department', 'designation', 'site', 'entity').prefetch_related('salary_structure__components')
            
            for emp_record in emps:
                missing_fields = []
                struct = resolve_employee_salary_structure(emp_record, default_structure)
                if not struct or struct.components.count() == 0:
                    missing_fields.append("Salary Structure")
                if not emp_record.ctc or emp_record.ctc <= 0:
                    missing_fields.append("CTC")
                
                if missing_fields:
                    missing_employees.append({
                        'id': emp_record.id,
                        'code': emp_record.code or f"EMP{emp_record.id}",
                        'name': f"{emp_record.first_name} {emp_record.last_name}".strip() or "Unnamed",
                        'department': emp_record.department.name if emp_record.department else 'N/A',
                        'designation': emp_record.designation.title if emp_record.designation else 'N/A',
                        'entity': entity.name,
                        'entity_id': entity.id,
                        'missing': missing_fields,
                        'missing_salary_structure': "Salary Structure" in missing_fields,
                        'missing_ctc': "CTC" in missing_fields,
                    })
        
        return Response({
            'status': 'success',
            'can_run': len(missing_employees) == 0,
            'missing_employees': missing_employees
        })

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        user = request.user
        from authentication.permissions import user_can_approve
        if not user_can_approve(user, module='Run Payroll'):
            return Response({'error': 'Permission denied. You do not have permission to approve payroll.'}, status=403)

        run = self.get_object()
        if run.status != 'Maker-Submitted':
            return Response({'error': 'Can only approve Maker-Submitted runs'}, status=400)
            
        run.status = 'Disbursed'
        run.checker = request.user
        run.save()
        
        # Mark approved reimbursements as Paid for employees who got a payslip in this run
        from .models import Reimbursement
        paid_employees = run.payslip_set.values_list('employee_id', flat=True)
        Reimbursement.objects.filter(employee_id__in=paid_employees, status='Approved').update(status='Paid')
        
        comment_text = request.data.get('comment', 'Approved')
        from .models import PayrollRunComment
        PayrollRunComment.objects.create(
            run=run,
            author=request.user,
            comment=f"Approved: {comment_text}" if comment_text and comment_text != 'Approved' else "Approved"
        )
        
        from employees.models import Notification
        for emp in Employee.objects.filter(status='Active'):
            if emp.dynamic_role and emp.dynamic_role.permissions and emp.dynamic_role.permissions.get('can_release_salary') in [True, 'true', 'True', 1, '1']:
                Notification.objects.create(
                    recipient=emp,
                    title="Payroll Approved",
                    message=f"Payroll for {run.period} has been approved by the CEO and is pending finance disbursement.",
                    related_run_id=run.id
                )
                
            if run.maker and hasattr(run.maker, 'employee_profile'):
                Notification.objects.create(
                    recipient=run.maker.employee_profile,
                    title="Payroll Approved",
                    message=f"Your payroll run for {run.period} was approved and forwarded to Finance.",
                    related_run_id=run.id
                )
                
        return Response({'status': 'success', 'run_status': run.status})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        user = request.user
        from authentication.permissions import user_can_approve
        if not user_can_approve(user, module='Run Payroll'):
            return Response({'error': 'Permission denied. You do not have permission to reject payroll.'}, status=403)

        run = self.get_object()
        if run.status != 'Maker-Submitted':
            return Response({'error': 'Can only reject Maker-Submitted runs'}, status=400)
            
        comment_text = request.data.get('comment')
        if not comment_text:
            return Response({'error': 'Comment is required'}, status=400)
            
        from .models import PayrollRunComment
        PayrollRunComment.objects.create(
            run=run,
            author=request.user,
            comment=comment_text
        )
            
        run.status = 'Draft'
        run.save()
        
        if run.maker and hasattr(run.maker, 'employee_profile'):
            from employees.models import Notification
            Notification.objects.create(
                recipient=run.maker.employee_profile,
                title="Payroll Rejected",
                message=f"Payroll for {run.period} was rejected. Reason: {comment_text}",
                related_run_id=run.id
            )
                
        return Response({'status': 'success', 'run_status': run.status})

class LoanViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Loans & Advances'
    queryset = Loan.objects.all()
    serializer_class = LoanSerializer

from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

class ReimbursementViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Reimbursements'
    queryset = Reimbursement.objects.all()
    serializer_class = ReimbursementSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

class SalarySlipAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.is_superuser:
            return Response({'error': 'Super admin does not have employee payslips'}, status=403)
        try:
            period = request.query_params.get('period')
            from .models import Payslip
            user = request.user
            from authentication.permissions import isolate_queryset
            
            can_view_confidential = False
            emp_profile = getattr(user, 'employee_profile', None)
            if emp_profile:
                if emp_profile.dynamic_role and emp_profile.dynamic_role.permissions:
                    perms = emp_profile.dynamic_role.permissions
                    can_view_confidential = perms.get('can_view_confidential_payroll') in [True, 'true', 'True', 1, '1'] or perms.get('can_view_confidential') in [True, 'true', 'True', 1, '1']
                elif emp_profile.role in ['admin', 'org_admin'] or getattr(emp_profile, 'is_admin', False):
                    can_view_confidential = True
            
            # Determine all periods where payroll has been run or payslips exist
            from payroll.models import PayrollRun
            run_periods = set(filter(None, isolate_queryset(PayrollRun.objects.all(), user).values_list('period', flat=True)))
            slip_periods = set(filter(None, isolate_queryset(Payslip.objects.all(), user).values_list('period', flat=True)))
            all_available_periods = sorted(list(run_periods | slip_periods), reverse=True)
            
            # If period was missing, check if latest run/slip exists in isolated scope
            if not request.query_params.get('period'):
                if all_available_periods:
                    period = all_available_periods[0]
                else:
                    from django.utils import timezone
                    period = timezone.now().strftime('%Y-%m')
                    
        except Exception as e:
            import traceback
            print("Payroll Query Error:", traceback.format_exc())
            raise e
        
        try:
            import calendar
            from datetime import date
            
            p_year, p_month = map(int, period.split('-'))
            _, total_days_in_month = calendar.monthrange(p_year, p_month)
            month_start = date(p_year, p_month, 1)
            month_end = date(p_year, p_month, total_days_in_month)
            calc_end = month_end
            db_slips = isolate_queryset(Payslip.objects.all(), user).filter(period=period).select_related('employee', 'employee__manager', 'employee__department').prefetch_related('lines', 'lines__rule')
            
            # Determine if we should dynamically calculate
            from payroll.models import PayrollRun
            run = PayrollRun.objects.filter(period=period).first()
            is_draft = run and run.status == 'Draft'
            
            # Precompute data for dynamic calculation if needed
            precomputed_data = {}
            if is_draft:
                from payroll.service import PayrollService
                precomputed_data = PayrollService._precompute_payroll_data(run)
                from payroll.engine import build_dag_and_sort

            slips = []
            
            # If no slips exist yet (but a run exists) we can preview for all isolated employees
            if not db_slips and is_draft:
                from django.db.models import Q
                preview_emps = isolate_queryset(Employee.objects.filter(status='Active'), user).filter(
                    Q(entity=run.entity) | Q(branch__entity=run.entity) | Q(site__branch__entity=run.entity)
                )
                db_slips = [Payslip(employee=e, run=run, period=period) for e in preview_emps]

            from attendance.models import DailyAttendance

            for slip in db_slips:
                emp = slip.employee
                components = {}
                paid_leave_days = 0
                
                if is_draft:
                    # DYNAMIC PREVIEW: Calculate 100% real-time using current CTC and formulas
                    try:
                        emp_rules = list(emp.salary_structure.components.all()) if getattr(emp, 'salary_structure', None) else []
                        emp._cached_dag = build_dag_and_sort(emp_rules) if emp_rules else []
                        gross, ded, net, line_items = PayrollService.process_employee_in_memory(emp, run, precomputed_data, is_simulation=True)
                        slip.gross = gross
                        slip.deductions = ded
                        slip.net = net
                        for item in line_items:
                            components[item['rule'].name.strip()] = item['amount']
                    except Exception as e:
                        # Fallback to empty if calculation fails
                        slip.gross = 0
                        slip.deductions = 0
                        slip.net = 0
                        slip.engine_error = str(e)
                else:
                    # DATABASE SNAPSHOT
                    try:
                        for line in slip.lines.all():
                            name = line.rule.name.strip()
                            if name in components:
                                components[f"{name} (2)"] = line.amount
                            else:
                                components[name] = line.amount
                    except ValueError:
                        pass
                
                emp_doj = emp.doj if emp.doj else month_start
                
                if emp_doj > calc_end:
                    days_paid, days_present, days_off, days_absent = 0, 0, 0, 0
                else:
                    calc_start = max(month_start, emp_doj)
                    calc_days = (calc_end - calc_start).days + 1
                    days_off = sum(1 for i in range(calc_days) if date.fromordinal(calc_start.toordinal() + i).weekday() == 6)
                    
                    # Fix: calculate absences by counting present/late days, rather than relying on explicit 'Absent' records.
                    # Dynamic Punch-Driven Model
                    present_count = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        attendance_status__in=['Present', 'Late']
                    ).count()
                    
                    half_day_count = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        attendance_status='Half Day'
                    ).count()
                    
                    absent_count = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        attendance_status='Absent'
                    ).count()

                    late_count = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        attendance_status='Late'
                    ).count()
                    late_penalty_days = (late_count // 3) * 0.5
                    
                    from django.db.models import Sum
                    ot_agg = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end
                    ).aggregate(total_ot=Sum('overtime_hours'))
                    total_ot_hours = ot_agg['total_ot'] or 0.0
                    
                    paid_leave_days = sum((min(l.end_date, calc_end) - max(l.start_date, calc_start)).days + 1 for l in emp.leave_requests.filter(status='Approved', start_date__lte=calc_end, end_date__gte=calc_start) if 'lop' not in (l.leave_type.name or '').lower())
                    
                    lop_days = sum((min(l.end_date, calc_end) - max(l.start_date, calc_start)).days + 1 for l in emp.leave_requests.filter(status='Approved', start_date__lte=calc_end, end_date__gte=calc_start) if 'lop' in (l.leave_type.name or '').lower())
                    
                    worked_days = float(present_count) + (float(half_day_count) * 0.5)
                    
                    if worked_days == 0 and paid_leave_days == 0:
                        days_paid = 0
                        days_present = 0
                        days_absent = calc_days
                    else:
                        days_present = min(worked_days, calc_days)
                        days_paid = max(0.0, min(worked_days + float(days_off) + float(paid_leave_days) - float(absent_count) - float(lop_days) - float(late_penalty_days), float(calc_days)))
                        days_absent = max(0.0, calc_days - days_paid)
                
                # Use the exact DB snapshot values without applying a secondary proration
                slip_gross = float(slip.gross)
                slip_ded = float(slip.deductions)
                slip_net = float(slip.net)
                
                for k in components:
                    components[k] = float(components[k])
                
                # Retroactive Fix: If an employee was saved with full salary but actually had 0 paid days due to the old bug, zero it out dynamically here.
                if days_paid == 0:
                    slip_gross = 0.0
                    slip_ded = 0.0
                    slip_net = 0.0
                    for k in components:
                        components[k] = 0.0
                        
                is_own_slip = (getattr(user, 'employee_profile', None) and user.employee_profile.id == emp.id)
                hide_money = not can_view_confidential and not is_own_slip

                actual_components = {}
                actual_gross = 0.0
                if getattr(emp, 'salary_structure', None) and emp.salary_structure.components.exists():
                    try:
                        struct_rules = list(emp.salary_structure.components.all())
                        from payroll.engine import build_dag_and_sort, evaluate_component
                        sorted_rules = build_dag_and_sort(struct_rules)
                        base_ctx = {
                            'ctc': Decimal(str(emp.ctc or 0)),
                            'monthly_ctc': Decimal(str(emp.ctc or 0)) / Decimal(12),
                            'present_days': Decimal(str(calc_days)),
                            'total_days': Decimal(str(calc_days)),
                            'paid_days': Decimal(str(calc_days)),
                            'overtime_hours': Decimal('0.00'),
                            'ot_hours': Decimal('0.00'),
                            'absent_days': Decimal('0.00'),
                            'lop_days': Decimal('0.00'),
                            'half_day_count': Decimal('0.00'),
                            'late_penalty_days': Decimal('0.00'),
                            'paid_leave_days': Decimal('0.00'),
                            'basic': Decimal('0.00'),
                            'hra': Decimal('0.00'),
                            'non_balancing_gross': Decimal('0.00'),
                        }
                        for r in sorted_rules:
                            base_ctx['non_balancing_gross'] = sum(base_ctx.get(other.name, Decimal('0')) for other in sorted_rules if other.type == 'Earning' and other.calc != 'Balancing')
                            actual_val = evaluate_component(r, base_ctx)
                            base_ctx[r.name] = actual_val
                            if r.type == 'Earning':
                                actual_components[r.name.strip()] = float(actual_val)
                                actual_gross += float(actual_val)
                    except Exception:
                        pass

                for k, v in components.items():
                    if k not in actual_components:
                        if days_paid > 0 and days_paid < calc_days:
                            act_val = round((float(v) / float(days_paid)) * float(calc_days), 2)
                        else:
                            act_val = float(v)
                        actual_components[k] = act_val
                        actual_gross += act_val

                if actual_gross == 0:
                    actual_gross = float(emp.ctc or 0) / 12.0 if emp.ctc else slip_gross

                entity_obj = None
                if getattr(emp, 'entity', None):
                    entity_obj = emp.entity
                elif getattr(slip, 'run', None) and getattr(slip.run, 'entity', None):
                    entity_obj = slip.run.entity
                elif getattr(emp, 'department', None) and getattr(emp.department, 'entity', None):
                    entity_obj = emp.department.entity
                elif getattr(emp, 'branch', None) and getattr(emp.branch, 'entity', None):
                    entity_obj = emp.branch.entity
                elif getattr(emp, 'site', None) and getattr(emp.site, 'branch', None) and getattr(emp.site.branch, 'entity', None):
                    entity_obj = emp.site.branch.entity
                elif getattr(emp, 'organization', None):
                    entity_obj = emp.organization

                entity_name = entity_obj.name if entity_obj else ''
                if not entity_name:
                    from authentication.permissions import isolate_queryset
                    first_ent = isolate_queryset(Entity.objects.all(), user).first()
                    if first_ent:
                        entity_name = first_ent.name

                slips.append({
                    'id': slip.id,
                    'empId': emp.id,
                    'firstName': emp.first_name,
                    'lastName': emp.last_name,
                    'code': emp.code,
                    'email': emp.email,
                    'entityName': entity_name,
                    'designation': emp.designation.title if getattr(emp, 'designation', None) else 'N/A',
                    'location': emp.site.name if getattr(emp, 'site', None) else (emp.entity.name if getattr(emp, 'entity', None) else 'Bangalore'),
                    'isConfidential': hide_money,
                    'ctc': 0 if hide_money else emp.ctc,
                    'gross': 0 if hide_money else slip_gross,
                    'actual_gross': 0 if hide_money else actual_gross,
                    'components': {} if hide_money else components,
                    'actual_components': {} if hide_money else actual_components,
                    'basic': 0 if hide_money else components.get('basic', 0),
                    'hra': 0 if hide_money else components.get('hra', 0),
                    'special': 0 if hide_money else components.get('special', 0),
                    'pf': 0 if hide_money else components.get('pf', components.get('Provident Fund', 0)),
                    'pt': 0 if hide_money else components.get('pt', components.get('Professional Tax', 0)),
                    'tds': 0 if hide_money else components.get('tds', components.get('Income Tax', 0)),
                    'ded': 0 if hide_money else slip_ded,
                    'net': 0 if hide_money else slip_net,
                    'arrears': 0 if hide_money else components.get('Retroactive Arrears', 0),
                    'bankName': emp.bank_name,
                    'bankAccount': emp.bank_account,
                    'pan': emp.pan,
                    'uan': emp.uan,
                    'doj': emp.doj,
                    'managerName': f"{emp.manager.first_name} {emp.manager.last_name}" if emp.manager else "—",
                    'department': emp.department.name if emp.department else 'N/A',
                    'totalDays': calc_days if 'calc_days' in locals() else 30,
                    'daysPaid': days_paid,
                    'daysPresent': days_present,
                    'daysOff': days_off,
                    'holidays': float(days_off),
                    'paidLeaves': float(paid_leave_days),
                    'daysAbsent': days_absent,
                    'lopDays': float(lop_days),
                    'extraDays': float(round(float(total_ot_hours) / 8.0, 2)) if 'total_ot_hours' in locals() else 0.0,
                    'lateMarks': int(late_count),
                    'latePenalties': float(late_penalty_days),
                    'halfDays': float(half_day_count),
                    'ot': float(total_ot_hours) if 'total_ot_hours' in locals() else 0.0,
                    'overtimeHours': float(total_ot_hours) if 'total_ot_hours' in locals() else 0.0,
                    'overtimePay': 0 if hide_money else float(components.get('Overtime Allowance', 0) or components.get('Overtime Pay', 0) or components.get('Overtime', 0)),
                    'error': getattr(slip, 'engine_error', None),
                    'leaveBalances': [
                        {
                            'type': lb.leave_type.name,
                            'allocated': float(lb.allocated_days),
                            'used': float(lb.used_days),
                            'remaining': float(lb.remaining_days)
                        } for lb in emp.leave_balances.filter(year=p_year)
                    ] if hasattr(emp, 'leave_balances') else []
                })
            diagnostics = {
                'total_payslips_in_db': Payslip.objects.count(),
                'slips_for_period': len(db_slips) if isinstance(db_slips, list) else db_slips.count(),
                'total_employees': Employee.objects.count(),
                'active_employees': Employee.objects.filter(status='Active').count(),
                'employee_details': list(Employee.objects.values('id', 'code', 'entity_id', 'status', 'ctc')),
                'payroll_runs': list(PayrollRun.objects.values('id', 'period', 'entity_id', 'status')),
                'exceptions': list(PayrollException.objects.values('error_trace').order_by('-id')[:20])
            }
            if period and period not in all_available_periods:
                all_available_periods.insert(0, period)
            return Response({ 'period': period, 'slips': slips, 'availablePeriods': all_available_periods, 'diagnostics': diagnostics })
        except Exception as e:
            import traceback
            print("Payroll Process Error:", traceback.format_exc())
            raise e

from django.http import HttpResponse

class PayslipPDFView(APIView):
    def get(self, request, pk=None):
        from .models import Payslip
        from authentication.permissions import isolate_queryset
        try:
            # isolate_queryset will filter Payslips the user is authorized to see
            qs = isolate_queryset(Payslip.objects.all(), request.user)
            slip = qs.select_related('employee', 'employee__department').prefetch_related('lines', 'lines__rule').get(pk=pk)
        except Payslip.DoesNotExist:
            return Response({'error': 'Payslip not found or unauthorized'}, status=404)
                
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="payslip_{slip.period}_{slip.employee.code}.pdf"'
        
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            
            p = canvas.Canvas(response, pagesize=letter)
            width, height = letter
            
            p.setFont("Helvetica-Bold", 16)
            p.drawString(50, height - 50, f"Payslip for {slip.period}")
            
            p.setFont("Helvetica", 12)
            p.drawString(50, height - 80, f"Employee Name: {slip.employee.first_name} {slip.employee.last_name}")
            p.drawString(50, height - 100, f"Employee Code: {slip.employee.code}")
            p.drawString(50, height - 120, f"Department: {slip.employee.department.name if slip.employee.department else 'N/A'}")
            
            # Show Overtime Hours if recorded for this period
            try:
                import calendar
                from datetime import date
                from django.db.models import Sum
                from attendance.models import DailyAttendance
                p_yr, p_mo = map(int, slip.period.split('-'))
                _, t_days = calendar.monthrange(p_yr, p_mo)
                m_start = date(p_yr, p_mo, 1)
                m_end = date(p_yr, p_mo, t_days)
                ot_sum = DailyAttendance.objects.filter(
                    employee=slip.employee,
                    attendance_date__gte=m_start,
                    attendance_date__lte=m_end
                ).aggregate(total_ot=Sum('overtime_hours'))['total_ot'] or 0.0
                if ot_sum > 0:
                    p.drawString(320, height - 100, f"Overtime Hours: {ot_sum} hrs")
                
                late_count = DailyAttendance.objects.filter(
                    employee=slip.employee,
                    attendance_date__gte=m_start,
                    attendance_date__lte=m_end,
                    attendance_status='Late'
                ).count()
                if late_count > 0:
                    p.drawString(320, height - 120, f"Late Marks: {late_count} marks")
            except Exception:
                pass
            
            p.drawString(50, height - 160, "Earnings & Deductions")
            
            y = height - 190
            for line in slip.lines.all():
                sign = "+" if line.rule.type == 'Earning' else "-"
                p.drawString(50, y, f"{line.rule.name}: {sign} {line.amount}")
                y -= 20
                
            y -= 20
            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y, f"Total Gross: {slip.gross}")
            y -= 20
            p.drawString(50, y, f"Total Deductions: {slip.deductions}")
            y -= 20
            p.drawString(50, y, f"Net Pay: {slip.net}")
            
            p.showPage()
            p.save()
            return response
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class PayslipEmailView(APIView):
    def post(self, request, pk=None):
        from .models import Payslip
        from authentication.permissions import isolate_queryset
        try:
            qs = isolate_queryset(Payslip.objects.all(), request.user)
            slip = qs.select_related('employee', 'employee__department').prefetch_related('lines', 'lines__rule').get(pk=pk)
        except Payslip.DoesNotExist:
            return Response({'error': 'Payslip not found or unauthorized'}, status=404)
            
        try:
            import io
            import base64
            from django.core.mail import EmailMessage
            from django.conf import settings
            
            pdf_datauri = request.data.get('pdf')
            if pdf_datauri and ',' in pdf_datauri:
                base64_data = pdf_datauri.split(',')[1]
                pdf_bytes = base64.b64decode(base64_data)
            else:
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter
                buffer = io.BytesIO()
                p = canvas.Canvas(buffer, pagesize=letter)
                width, height = letter
                
                p.setFont("Helvetica-Bold", 16)
                p.drawString(50, height - 50, f"Payslip for {slip.period}")
                
                p.setFont("Helvetica", 12)
                p.drawString(50, height - 80, f"Employee Name: {slip.employee.first_name} {slip.employee.last_name}")
                p.drawString(50, height - 100, f"Employee Code: {slip.employee.code}")
                p.drawString(50, height - 120, f"Department: {slip.employee.department.name if slip.employee.department else 'N/A'}")
                p.drawString(50, height - 160, "Earnings & Deductions")
                
                y = height - 190
                for line in slip.lines.all():
                    sign = "+" if line.rule.type == 'Earning' else "-"
                    p.drawString(50, y, f"{line.rule.name}: {sign} {line.amount}")
                    y -= 20
                    
                y -= 20
                p.setFont("Helvetica-Bold", 12)
                p.drawString(50, y, f"Total Gross: {slip.gross}")
                y -= 20
                p.drawString(50, y, f"Total Deductions: {slip.deductions}")
                y -= 20
                p.drawString(50, y, f"Net Pay: {slip.net}")
                
                p.showPage()
                p.save()
                pdf_bytes = buffer.getvalue()
                buffer.close()
            
            email = EmailMessage(
                f"Your Payslip for {slip.period}",
                f"Hello {slip.employee.first_name},\n\nPlease find attached your payslip for the period {slip.period}.\n\nRegards,\nHRMS PeoplePulse",
                settings.EMAIL_HOST_USER,
                [slip.employee.email]
            )
            email.attach(f'payslip_{slip.period}_{slip.employee.code}.pdf', pdf_bytes, 'application/pdf')
            
            import threading
            threading.Thread(target=email.send).start()
            
            
            return Response({'message': 'Payslip emailed successfully!'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class PayrollPreviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            period = request.query_params.get('period')
            entity_param = request.query_params.get('entity')
            include_leaves_encashment_str = request.query_params.get('include_leaves_encashment', 'false')
            include_leaves_encashment = include_leaves_encashment_str.lower() == 'true'
            
            if not period:
                return Response({'error': 'Period is required'}, status=400)
                           # Direct check for can_view_confidential without empty serializer context
            user = request.user
            can_view_confidential = False
            if user and user.is_authenticated:
                if user.is_superuser:
                    can_view_confidential = True
                else:
                    emp = getattr(user, 'employee_profile', None)
                    if emp:
                        if emp.role == 'super_admin':
                            can_view_confidential = True
                        elif emp.dynamic_role and emp.dynamic_role.permissions:
                            perms = emp.dynamic_role.permissions
                            can_view_confidential = perms.get('can_view_confidential_payroll') in [True, 'true', 'True', 1, '1'] or perms.get('can_view_confidential') in [True, 'true', 'True', 1, '1']
                        elif emp.role in ['admin', 'org_admin'] or getattr(emp, 'is_admin', False):
                            can_view_confidential = True
            
            from organisation.models import Entity
            from payroll.models import PayrollRun
            from employees.models import Employee
            from payroll.service import PayrollService
            from payroll.engine import build_dag_and_sort
            from decimal import Decimal

            if entity_param and entity_param != '__all__':
                entity_ids = entity_param.split(',')
                entities = Entity.objects.filter(id__in=entity_ids)
            else:
                entities = Entity.objects.all()

            results = []

            for entity in entities:
                # Create a mock run for precomputation
                run = PayrollRun(period=period, entity=entity, status='Draft')
                precomputed_data = PayrollService._precompute_payroll_data(run)
                
                from authentication.permissions import isolate_queryset
                from django.db.models import Q
                employees = isolate_queryset(Employee.objects.filter(status='Active'), request.user).filter(
                    Q(entity=entity) | Q(branch__entity=entity) | Q(site__branch__entity=entity)
                ).select_related('salary_structure').prefetch_related('salary_structure__components')
                
                emp_count = 0
                total_gross = Decimal('0.00')
                total_deductions = Decimal('0.00')
                total_net = Decimal('0.00')
                
                dag_cache = {}
                errors = []
                employee_details = []
                missing_in_entity = []
                from payroll.models import SalaryStructure
                default_structure = SalaryStructure.objects.filter(status='Active').first()
                for emp in employees:
                    try:
                        struct = resolve_employee_salary_structure(emp, default_structure)
                        missing_fields = []
                        if not struct or struct.components.count() == 0:
                            missing_fields.append("Salary Structure")
                        if not emp.ctc or emp.ctc <= 0:
                            missing_fields.append("CTC")
                        
                        safe_name = f"{getattr(emp, 'first_name', '')} {getattr(emp, 'last_name', '')}".strip()
                        safe_dept = emp.department.name if getattr(emp, 'department', None) else ''
                        
                        if missing_fields:
                            missing_in_entity.append({
                                'id': emp.id,
                                'code': emp.code or f"EMP{emp.id}",
                                'name': safe_name or f"{emp.first_name} {emp.last_name}".strip(),
                                'department': safe_dept or 'N/A',
                                'designation': emp.designation.title if getattr(emp, 'designation', None) else 'N/A',
                                'entity': entity.name,
                                'entity_id': entity.id,
                                'missing': missing_fields,
                                'missing_salary_structure': "Salary Structure" in missing_fields,
                                'missing_ctc': "CTC" in missing_fields,
                            })

                        assigned_struct = emp.salary_structure or struct
                        if assigned_struct:
                            emp.salary_structure = assigned_struct
                            if assigned_struct.id not in dag_cache:
                                emp_rules = list(assigned_struct.components.all())
                                dag_cache[assigned_struct.id] = build_dag_and_sort(emp_rules) if emp_rules else []
                            emp._cached_dag = dag_cache[assigned_struct.id]
                        else:
                            emp._cached_dag = []
                            
                        gross, ded, net, line_items = PayrollService.process_employee_in_memory(emp, run, precomputed_data, is_simulation=True, include_leaves_encashment=include_leaves_encashment)
                        total_gross += gross
                        total_deductions += ded
                        total_net += net
                        emp_count += 1
                        
                        context = PayrollService._get_context_for_employee(emp, precomputed_data)
                        
                        pf_amount = 0
                        pt_amount = 0
                        reimbursement = 0
                        incentive = 0
                        arrears = 0
                        ot_pay = 0
                        
                        try:
                            pf_amount = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and 'PF' in str(item['rule'].name).upper())
                            pt_amount = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and ('PT' in str(item['rule'].name).upper() or 'PROFESSIONAL TAX' in str(item['rule'].name).upper()))
                            reimbursement = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and 'REIMBURSEMENT' in str(item['rule'].name).upper())
                            incentive = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and ('INCENTIVE' in str(item['rule'].name).upper() or 'BONUS' in str(item['rule'].name).upper()))
                            arrears = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and 'ARREAR' in str(item['rule'].name).upper())
                            ot_pay = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and ('OVERTIME' in str(item['rule'].name).upper() or 'OT' in str(item['rule'].name).upper()))
                        except Exception as e:
                            print(f"Error summing items: {e}")
                        
                        hide_money = not can_view_confidential
                        
                        # SAFE EXTRACT
                        safe_email = getattr(emp, 'email', '')
                        safe_phone = getattr(emp, 'phone', '')
                        safe_site = emp.site.name if getattr(emp, 'site', None) else ''
                        if getattr(emp, 'entity', None): safe_entity = emp.entity.name
                        elif getattr(emp, 'branch', None) and getattr(emp.branch, 'entity', None): safe_entity = emp.branch.entity.name
                        elif getattr(emp, 'site', None) and getattr(emp.site, 'branch', None) and getattr(emp.site.branch, 'entity', None): safe_entity = emp.site.branch.entity.name
                        else: safe_entity = ''
                        safe_bank = getattr(emp, 'bank_name', '')
                        safe_ac = getattr(emp, 'bank_account', '')
                        safe_ifsc = getattr(emp, 'ifsc', '')
                        
                        def sfloat(val):
                            try:
                                return float(val or 0)
                            except:
                                return 0.0

                        employee_details.append({
                            'id': emp.id,
                            'name': safe_name,
                            'code': emp.code or f"EMP{emp.id}",
                            'email': safe_email,
                            'number': safe_phone or '',
                            'workFrom': safe_site,
                            'entity': safe_entity,
                            'department': safe_dept,
                            'bankName': safe_bank or '',
                            'acNo': safe_ac or '',
                            'ifscCode': safe_ifsc or '',
                            'currentSalary': 0 if hide_money else sfloat(getattr(emp, 'ctc', 0)),
                            'totalDays': sfloat(context.get('total_days', 0)),
                            'presentDays': sfloat(context.get('actual_present_days', context.get('present_days', 0))),
                            'leaves': sfloat(context.get('annual_leaves', context.get('paid_leave_days', 0))),
                            'absentDays': sfloat(context.get('absent_days', 0)),
                            'lopDays': sfloat(context.get('lop_days', 0)),
                            'ot': sfloat(context.get('ot_hours', context.get('overtime_hours', 0))),
                            'overtimeHours': sfloat(context.get('ot_hours', context.get('overtime_hours', 0))),
                            'overtimePay': 0 if hide_money else sfloat(ot_pay),
                            'halfDays': sfloat(context.get('half_day_count', 0)),
                            'latePenalties': sfloat(context.get('late_penalty_days', 0)),
                            'daysPaid': sfloat(context.get('paid_days', 0)),
                            'totalAmount': 0 if hide_money else sfloat(gross),
                            'arrears': 0 if hide_money else sfloat(arrears),
                            'deduction': 0 if hide_money else sfloat(ded),
                            'pf': 0 if hide_money else sfloat(pf_amount),
                            'pt': 0 if hide_money else sfloat(pt_amount),
                            'reimbursement': 0 if hide_money else sfloat(reimbursement),
                            'incentive': 0 if hide_money else sfloat(incentive),
                            'payableSalary': 0 if hide_money else sfloat(net),
                            'isConfidential': hide_money,
                            'salaryStructure': assigned_struct.id if assigned_struct else None,
                            'salary_structure': assigned_struct.id if assigned_struct else None,
                            'missingFields': missing_fields,
                            'hasSalaryStructure': "Salary Structure" not in missing_fields,
                            'hasCtc': "CTC" not in missing_fields,
                            'isValidForRun': len(missing_fields) == 0,
                        })
                    except Exception as e:
                        import traceback
                        tb_str = traceback.format_exc()
                        print(f"DEBUG ERRORS for employee {emp.id}:", tb_str)
                        errors.append(f"Emp {emp.id}: {str(e)} | {tb_str}")
                        # Inject error into table for visibility
                        employee_details.append({
                            'id': emp.id, 'name': f"ERROR: {str(e)}", 'email': '', 'number': '',
                            'workFrom': '', 'entity': '', 'department': '', 'bankName': '', 'acNo': '',
                            'ifscCode': '', 'currentSalary': 0, 'totalDays': 0, 'presentDays': 0,
                            'totalAmount': 0, 'deduction': 0, 'pf': 0, 'pt': 0, 'reimbursement': 0,
                            'incentive': 0, 'payableSalary': 0, 'isConfidential': False,
                            'missingFields': ['Configuration error'],
                            'hasSalaryStructure': False,
                            'hasCtc': False,
                            'isValidForRun': False
                        })
                        emp_count += 1
                
                if errors:
                    print(f"DEBUG ERRORS for entity {entity.name}:", errors)

                if emp_count == 0:
                    pass

                results.append({
                    'entity': entity.name,
                    'employees': emp_count,
                    'gross': float(total_gross) if can_view_confidential else 0,
                    'deduction': float(total_deductions) if can_view_confidential else 0,
                    'net': float(total_net) if can_view_confidential else 0,
                    'isConfidential': not can_view_confidential,
                    'errors': errors[:5],  # send first 5 errors for debugging
                    'employee_details': employee_details,
                    'employeeDetails': employee_details, # Failsafe for OneClickPanel
                    'missing_employees': missing_in_entity,
                    'can_run': len(missing_in_entity) == 0
                })
                    
            all_missing = [m for r in results for m in r.get('missing_employees', [])]
            return Response({
                'status': 'success',
                'data': results,
                'can_run': len(all_missing) == 0,
                'missing_employees': all_missing
            })
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            # If the entire view crashes, return a fake result so the UI table shows the crash!
            fake_result = [{
                'entity': 'CRASH',
                'employees': 1,
                'gross': 0, 'deduction': 0, 'net': 0,
                'isConfidential': False,
                'errors': [str(e)],
                'employee_details': [{
                    'id': 9999, 'name': f"CRASH: {str(e)}", 'email': str(tb)[:50], 'number': '',
                    'workFrom': '', 'entity': '', 'department': '', 'bankName': '', 'acNo': '',
                    'ifscCode': '', 'currentSalary': 0, 'totalDays': 0, 'presentDays': 0,
                    'totalAmount': 0, 'deduction': 0, 'pf': 0, 'pt': 0, 'reimbursement': 0,
                    'incentive': 0, 'payableSalary': 0, 'isConfidential': False
                }],
                'employeeDetails': []
            }]
            return Response({'status': 'success', 'data': fake_result})

from .models import Form16Document
from .serializers import Form16DocumentSerializer
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

class Form16DocumentViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    queryset = Form16Document.objects.all().order_by('-uploaded_at')
    serializer_class = Form16DocumentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        emp = getattr(user, 'employee_profile', None)
        
        # Super admin cannot view site employee Form 16s
        if user.is_superuser:
            return qs.none()
            
        if emp and emp.role in ['org_admin', 'admin']:
            return qs
            
        # Regular employees can only see their own
        if emp:
            return qs.filter(employee=emp)
            
        return qs.none()
        
    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)

    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        files = request.FILES.getlist('files')
        financial_year = request.data.get('financial_year', '2025-26')
        mapping_mode = request.data.get('mapping_mode', 'filename')
        
        if not files:
            return Response({'error': 'No files provided'}, status=400)
            
        results = {'success': 0, 'failed': 0, 'errors': []}
        
        for file in files:
            # Simple filename parsing logic for demo: EMP0012_FORM16_2025-26.pdf
            filename = file.name
            emp_code = filename.split('_')[0] if '_' in filename else filename.split('.')[0]
            
            try:
                emp = Employee.objects.get(code=emp_code)
                
                # Check for existing
                existing = Form16Document.objects.filter(employee=emp, financial_year=financial_year).order_by('-version').first()
                version = existing.version + 1 if existing else 1
                
                Form16Document.objects.create(
                    employee=emp,
                    financial_year=financial_year,
                    version=version,
                    file=file,
                    uploaded_by=request.user,
                    status='Pending'
                )
                results['success'] += 1
            except Employee.DoesNotExist:
                results['failed'] += 1
                results['errors'].append(f"Employee not found for file {filename} (Code: {emp_code})")
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"Error processing {filename}: {str(e)}")
                
        return Response(results)

from .models import CTCImportHistory
from .serializers import CTCImportHistorySerializer
import csv
import io
import time
from rest_framework.parsers import MultiPartParser
from django.http import HttpResponse

class CTCImportHistoryViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Import CTC'
    permission_classes = [IsAuthenticated, IsHR]
    queryset = CTCImportHistory.objects.all().order_by('-import_date')
    serializer_class = CTCImportHistorySerializer

class ImportCTCTemplateView(APIView):
    rbac_module = 'Import CTC'
    permission_classes = [IsAuthenticated, IsHR]
    
    def get(self, request):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="CTC import template.csv"'
        writer = csv.writer(response)
        
        # Include fields for context to make filling out the template easier
        writer.writerow([
            'Employee Code', 'First Name', 'Last Name', 'Email', 'Department', 'Designation', 
            'CTC', 'Tax Regime', 'Tax Saving Deductions', 'Salary Structure', 
            'PF Applicable', 'Bonus Applicable', 'Bonus Type', 'Bonus Value', 'Bonus Months'
        ])
        
        # Output reference dummy rows instead of real employee data
        writer.writerow(['EMP-001', 'John', 'Doe', 'john@example.com', 'Engineering', 'Developer', '1200000', 'New', '0', 'Client Structure', 'Yes', 'Yes', 'Fixed Amount', '50000', '1'])
        writer.writerow(['EMP-002', 'Jane', 'Smith', 'jane@example.com', 'HR', 'Manager', '1500000', 'Old', '150000', 'Client Structure', 'No', 'No', '', '', ''])
                
        return response

class ImportCTCAPIView(APIView):
    rbac_module = 'Import CTC'
    permission_classes = [IsAuthenticated, IsHR]
    parser_classes = [MultiPartParser]

    def post(self, request, *args, **kwargs):
        file = request.FILES.get('file')
        if not file:
            return Response({"detail": "No file uploaded."}, status=400)
            
        if not file.name.endswith('.csv'):
            return Response({"detail": "Invalid format. Only .csv is supported."}, status=400)
            
        start_time = time.time()
        
        try:
            decoded_file = file.read().decode('utf-8')
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string)
        except Exception as e:
            return Response({"detail": "Invalid format or encoding."}, status=400)
            
        if not reader.fieldnames or 'Employee Code' not in reader.fieldnames or 'CTC' not in reader.fieldnames:
            return Response({"detail": "Invalid format. CSV must contain 'Employee Code' and 'CTC' columns."}, status=400)
            
        from authentication.permissions import isolate_queryset
        
        allowed_employees = isolate_queryset(Employee.objects.all(), request.user)
        allowed_employees_dict = {e.code: e for e in allowed_employees}
        
        successful = 0
        failed = 0
        
        for row in reader:
            code = row.get('Employee Code', '').strip()
            
            if not code:
                failed += 1
                continue
                
            emp = allowed_employees_dict.get(code)
            if not emp:
                failed += 1
                continue
                
            updated_fields = []
            
            ctc_val = row.get('CTC', '').strip()
            if ctc_val:
                try:
                    ctc = int(float(ctc_val))
                    emp.ctc = ctc
                    updated_fields.append('ctc')
                except ValueError:
                    pass
                    
            tax_regime = row.get('Tax Regime', '').strip()
            if tax_regime in dict(Employee.TAX_REGIME_CHOICES):
                emp.tax_regime = tax_regime
                updated_fields.append('tax_regime')
                
            tax_saving = row.get('Tax Saving Deductions', '').strip()
            if tax_saving:
                try:
                    emp.tax_saving_deductions = float(tax_saving)
                    updated_fields.append('tax_saving_deductions')
                except ValueError: pass
                
            struct_name = row.get('Salary Structure', '').strip()
            if struct_name:
                from payroll.models import SalaryStructure
                struct = SalaryStructure.objects.filter(name__iexact=struct_name).first()
                if struct:
                    emp.salary_structure = struct
                    updated_fields.append('salary_structure')
                    
            pf_app = row.get('PF Applicable', '').strip().lower()
            if pf_app in ['yes', 'true', '1']:
                emp.pf_applicable = True
                updated_fields.append('pf_applicable')
            elif pf_app in ['no', 'false', '0']:
                emp.pf_applicable = False
                updated_fields.append('pf_applicable')
                    
            bonus_app = row.get('Bonus Applicable', '').strip().lower()
            if bonus_app in ['yes', 'true', '1']:
                emp.bonus_applicable = True
                updated_fields.append('bonus_applicable')
            elif bonus_app in ['no', 'false', '0']:
                emp.bonus_applicable = False
                updated_fields.append('bonus_applicable')
                
            b_type = row.get('Bonus Type', '').strip()
            if b_type in dict(Employee.BONUS_TYPE_CHOICES):
                emp.bonus_type = b_type
                updated_fields.append('bonus_type')
                
            b_val = row.get('Bonus Value', '').strip()
            if b_val:
                try:
                    emp.bonus_value = float(b_val)
                    updated_fields.append('bonus_value')
                except ValueError: pass
                
            b_months = row.get('Bonus Months', '').strip()
            if b_months:
                try:
                    emp.bonus_months = int(float(b_months))
                    updated_fields.append('bonus_months')
                except ValueError: pass
                
            if updated_fields:
                emp.save(update_fields=updated_fields)
            
            try:
                from employees.models import CompensationHistory
                latest_history = emp.compensation_history.order_by('-effective_from').first()
                if latest_history:
                    CompensationHistory.objects.create(
                        employee=emp,
                        ctc=emp.ctc,
                        salary_structure=latest_history.salary_structure,
                        effective_from=timezone.now().date(),
                        reason="Bulk CTC Import",
                        changed_by=request.user
                    )
            except Exception as e:
                pass
                
            successful += 1
            
        duration = int(time.time() - start_time)
        status_val = 'Completed' if failed == 0 else ('Failed' if successful == 0 else 'Partial')
        
        CTCImportHistory.objects.create(
            imported_by=request.user,
            records_processed=successful + failed,
            successful=successful,
            failed=failed,
            file_type='CSV',
            duration_seconds=duration,
            status=status_val
        )
        
        return Response({
            "successful": successful,
            "failed": failed,
            "status": status_val
        })

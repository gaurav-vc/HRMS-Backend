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
        try:
            run = self.get_object()
            overrides = request.data.get('overrides')
            include_variable_bonus = request.data.get('include_variable_bonus', False)
            
            if run.status in ['Frozen', 'Disbursed']:
                if overrides:
                    PayrollService.file_arrears(run.id, overrides)
                return Response({'status': 'success', 'run_status': run.status, 'msg': 'Arrears processed'})
                
            run = PayrollService.execute_run(run.id, overrides=overrides, include_variable_bonus=include_variable_bonus)
            if hasattr(request, 'user') and request.user.is_authenticated:
                run.maker = request.user
                run.save()
            
            return Response({'status': 'success', 'run_status': run.status, 'msg': 'Engine started in background'})
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return Response({'status': 'error', 'message': f"CRASH: {str(e)} | Trace: {tb}"}, status=400)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
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
            if emp.dynamic_role and emp.dynamic_role.permissions and emp.dynamic_role.permissions.get('can_release_salary'):
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

class ReimbursementViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Reimbursements'
    queryset = Reimbursement.objects.all()
    serializer_class = ReimbursementSerializer

class SalarySlipAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            period = request.query_params.get('period')
            from .models import Payslip
            user = request.user
            from authentication.permissions import isolate_queryset
            
            can_view_confidential = False
            if user.is_superuser:
                can_view_confidential = True
            elif hasattr(user, 'employee_profile') and user.employee_profile:
                emp_profile = user.employee_profile
                if getattr(emp_profile, 'is_hr', False) or getattr(emp_profile, 'is_admin', False) or getattr(emp_profile, 'is_superadmin', False):
                    can_view_confidential = True
                elif getattr(emp_profile, 'dynamic_role', None):
                    perms = emp_profile.dynamic_role.permissions or {}
                    if perms.get('can_view_confidential_payroll') in [True, 'true', 'True', 1, '1']:
                        can_view_confidential = True
            
            # If period was missing, check if last_slip exists in isolated scope
            if not request.query_params.get('period'):
                last_slip = isolate_queryset(Payslip.objects.all(), user).order_by('-id').first()
                if last_slip:
                    period = last_slip.period
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
                        days_paid = max(0.0, min(worked_days + float(days_off) + float(paid_leave_days) - float(absent_count) - float(lop_days), float(calc_days)))
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

                slips.append({
                    'id': slip.id,
                    'empId': emp.id,
                    'firstName': emp.first_name,
                    'lastName': emp.last_name,
                    'code': emp.code,
                    'email': emp.email,
                    'entityName': emp.entity.name if emp.entity else (emp.site.branch.entity.name if emp.site and emp.site.branch and emp.site.branch.entity else ''),
                    'isConfidential': hide_money,
                    'ctc': 0 if hide_money else emp.ctc,
                    'gross': 0 if hide_money else slip_gross,
                    'components': {} if hide_money else components,
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
                    'paidLeaves': float(paid_leave_days),
                    'daysAbsent': days_absent,
                    'overtimeHours': float(total_ot_hours) if 'total_ot_hours' in locals() else 0.0,
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
                
            return Response({ 'period': period, 'slips': slips, 'diagnostics': diagnostics })
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
                        if getattr(emp, 'is_hr', False) or getattr(emp, 'is_admin', False) or getattr(emp, 'is_superadmin', False) or emp.role == 'super_admin':
                            can_view_confidential = True
                        elif emp.dynamic_role:
                            perms = emp.dynamic_role.permissions or {}
                            if perms.get('can_view_confidential_payroll') in [True, 'true', 'True', 1, '1'] or perms.get('can_view_confidential') in [True, 'true', 'True', 1, '1']:
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

            user = request.user
            can_view_confidential = False
            if user and user.is_authenticated:
                if user.is_superuser:
                    can_view_confidential = True
                else:
                    emp = getattr(user, 'employee_profile', None)
                    if emp:
                        if getattr(emp, 'is_hr', False) or getattr(emp, 'is_admin', False) or getattr(emp, 'is_superadmin', False) or emp.role == 'super_admin':
                            can_view_confidential = True
                        elif emp.dynamic_role:
                            perms = emp.dynamic_role.permissions or {}
                            if perms.get('can_view_confidential_payroll') in [True, 'true', 'True', 1, '1'] or perms.get('can_view_confidential') in [True, 'true', 'True', 1, '1']:
                                can_view_confidential = True
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
                for emp in employees:
                    try:
                        if emp.salary_structure:
                            if emp.salary_structure.id not in dag_cache:
                                emp_rules = list(emp.salary_structure.components.all())
                                dag_cache[emp.salary_structure.id] = build_dag_and_sort(emp_rules) if emp_rules else []
                            emp._cached_dag = dag_cache[emp.salary_structure.id]
                        else:
                            emp._cached_dag = []
                            
                        gross, ded, net, line_items = PayrollService.process_employee_in_memory(emp, run, precomputed_data, is_simulation=True)
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
                        
                        try:
                            pf_amount = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and 'PF' in str(item['rule'].name).upper())
                            pt_amount = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and ('PT' in str(item['rule'].name).upper() or 'PROFESSIONAL TAX' in str(item['rule'].name).upper()))
                            reimbursement = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and 'REIMBURSEMENT' in str(item['rule'].name).upper())
                            incentive = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and ('INCENTIVE' in str(item['rule'].name).upper() or 'BONUS' in str(item['rule'].name).upper()))
                            arrears = sum(item['amount'] for item in line_items if getattr(item['rule'], 'name', None) and 'ARREAR' in str(item['rule'].name).upper())
                        except Exception as e:
                            print(f"Error summing items: {e}")
                        
                        hide_money = not can_view_confidential
                        
                        # SAFE EXTRACT
                        safe_name = f"{getattr(emp, 'first_name', '')} {getattr(emp, 'last_name', '')}".strip()
                        safe_email = getattr(emp, 'email', '')
                        safe_phone = getattr(emp, 'phone', '')
                        safe_site = emp.site.name if getattr(emp, 'site', None) else ''
                        if getattr(emp, 'entity', None): safe_entity = emp.entity.name
                        elif getattr(emp, 'branch', None) and getattr(emp.branch, 'entity', None): safe_entity = emp.branch.entity.name
                        elif getattr(emp, 'site', None) and getattr(emp.site, 'branch', None) and getattr(emp.site.branch, 'entity', None): safe_entity = emp.site.branch.entity.name
                        else: safe_entity = ''
                        safe_dept = emp.department.name if getattr(emp, 'department', None) else ''
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
                            'leaves': sfloat(context.get('absent_days', 0)),
                            'lopDays': sfloat(context.get('lop_days', 0)),
                            'ot': sfloat(context.get('ot_hours', context.get('overtime_hours', 0))),
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
                            'isConfidential': hide_money
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
                            'incentive': 0, 'payableSalary': 0, 'isConfidential': False
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
                    'employeeDetails': employee_details # Failsafe for OneClickPanel
                })
                    
            return Response({'status': 'success', 'data': results})
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

class Form16DocumentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    queryset = Form16Document.objects.all().order_by('-uploaded_at')
    serializer_class = Form16DocumentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        emp = getattr(user, 'employee_profile', None)
        
        # Super admins and HR can see all
        if user.is_superuser or user.is_staff or (emp and emp.role in ['super_admin', 'org_admin']):
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
    permission_classes = [IsAuthenticated, IsHR]
    queryset = CTCImportHistory.objects.all().order_by('-import_date')
    serializer_class = CTCImportHistorySerializer

class ImportCTCTemplateView(APIView):
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

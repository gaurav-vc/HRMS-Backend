from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, Count
from django.utils import timezone
from authentication.permissions import DataIsolationMixin
from rest_framework.permissions import IsAuthenticated
from employees.models import Employee
from payroll.models import Payslip, PayslipAllocationSnapshot, PayslipLineItem
from attendance.models import DailyAttendance
import csv
from django.http import HttpResponse

class DashboardView(DataIsolationMixin, APIView):
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        # We need a dummy queryset for DataIsolationMixin, but we'll apply logic manually
        return Employee.objects.all()

    def get(self, request):
        user = request.user
        emp = getattr(user, 'employee_profile', None)
        
        # Base filter based on user role (simulating DataIsolation)
        emp_filter = {}
        if not user.is_superuser and emp:
            if emp.role == 'org_admin':
                emp_filter['entity'] = emp.entity
            elif emp.role == 'site_admin':
                emp_filter['site'] = emp.site
            elif emp.role in ['hr', 'manager']:
                emp_filter['entity'] = emp.entity
        
        # Employee metrics
        total_employees = Employee.objects.filter(status='Active', **emp_filter).count()
        new_joiners = Employee.objects.filter(
            status='Active', 
            doj__gte=timezone.now().date().replace(day=1),
            **emp_filter
        ).count()
        
        # Attendance metrics for today
        today = timezone.now().date()
        present_today = DailyAttendance.objects.filter(
            attendance_date=today,
            attendance_status__in=['Present', 'Late'],
            employee__status='Active',
            **{f"employee__{k}": v for k, v in emp_filter.items()}
        ).count()
        
        # Payroll metrics for current month
        period = today.strftime('%Y-%m')
        total_payroll_qs = Payslip.objects.filter(
            period=period,
            **{f"employee__{k}": v for k, v in emp_filter.items()}
        ).aggregate(
            total_net=Sum('net'),
            total_gross=Sum('gross'),
            total_deductions=Sum('deductions')
        )
        
        return Response({
            'headcount': {
                'total': total_employees,
                'new_joiners_this_month': new_joiners
            },
            'attendance_today': {
                'present_count': present_today,
                'estimated_absent': max(0, total_employees - present_today)
            },
            'payroll_current_month': {
                'period': period,
                'total_net': total_payroll_qs['total_net'] or 0,
                'total_gross': total_payroll_qs['total_gross'] or 0,
                'total_deductions': total_payroll_qs['total_deductions'] or 0
            }
        })

class StatutoryRegisterView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Export CSV for PF/ESI Statutory compliance.
        Format: Emp Code, Name, UAN, Gross, PF Deduction
        """
        # Ensure only HR/Admins can access this
        user = request.user
        emp = getattr(user, 'employee_profile', None)
        if not user.is_superuser and (not emp or emp.role not in ['super_admin', 'org_admin', 'hr']):
            return Response({'error': 'Unauthorized'}, status=403)
            
        period = request.query_params.get('period')
        if not period:
            return Response({'error': 'Period is required (YYYY-MM)'}, status=400)
            
        slip_filter = {'period': period}
        if not user.is_superuser and emp.role != 'super_admin':
            slip_filter['employee__entity'] = emp.entity
            
        slips = Payslip.objects.filter(**slip_filter).select_related('employee').prefetch_related('lines', 'lines__rule')
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="statutory_register_{period}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Employee Code', 'Employee Name', 'UAN', 'PAN', 'Gross Pay', 'PF Deduction', 'PT Deduction', 'Net Pay'])
        
        for slip in slips:
            pf_amount = 0
            pt_amount = 0
            for line in slip.lines.all():
                name = line.rule.name.strip().lower()
                if 'pf' in name or 'provident' in name:
                    pf_amount = line.amount
                elif 'pt' in name or 'professional' in name:
                    pt_amount = line.amount
                    
            writer.writerow([
                slip.employee.code,
                f"{slip.employee.first_name} {slip.employee.last_name}",
                slip.employee.uan or 'N/A',
                slip.employee.pan or 'N/A',
                slip.gross,
                pf_amount,
                pt_amount,
                slip.net
            ])
            
        return response

class CostCenterReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Aggregate payroll costs by Cost Center using Allocation Snapshots.
        """
        user = request.user
        emp = getattr(user, 'employee_profile', None)
        if not user.is_superuser and (not emp or emp.role not in ['super_admin', 'org_admin', 'hr']):
            return Response({'error': 'Unauthorized'}, status=403)
            
        period = request.query_params.get('period')
        if not period:
            return Response({'error': 'Period is required (YYYY-MM)'}, status=400)
            
        slip_filter = {'payslip__period': period}
        if not user.is_superuser and emp.role != 'super_admin':
            slip_filter['payslip__employee__entity'] = emp.entity
            
        snapshots = PayslipAllocationSnapshot.objects.filter(**slip_filter).select_related('cost_center', 'payslip')
        
        # Aggregate manually to apply percentage accurately
        # OR mathematically: sum(payslip.gross * percentage / 100)
        from collections import defaultdict
        cost_centers = defaultdict(lambda: {'gross': 0, 'net': 0})
        
        for snap in snapshots:
            ratio = snap.percentage / 100
            cc_name = snap.cost_center.name
            cost_centers[cc_name]['gross'] += float(snap.payslip.gross) * float(ratio)
            cost_centers[cc_name]['net'] += float(snap.payslip.net) * float(ratio)
            
        results = [
            {
                'cost_center': name, 
                'total_gross': round(data['gross'], 2), 
                'total_net': round(data['net'], 2)
            } 
            for name, data in cost_centers.items()
        ]
        
        return Response({
            'period': period,
            'cost_center_allocations': results
        })

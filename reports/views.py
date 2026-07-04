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

class PayrollAttendanceReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import calendar
        from datetime import date
        from django.db.models import Sum
        from employees.models import Employee
        from attendance.models import DailyAttendance
        from payroll.models import Payslip
        
        user = request.user
        emp = getattr(user, 'employee_profile', None)
        
        # Verify permissions
        if not user.is_superuser and (not emp or emp.role not in ['super_admin', 'org_admin', 'hr', 'manager']):
            return Response({'error': 'Unauthorized'}, status=403)
            
        today = date.today()
        
        # Find the most recent month with Payslip data to ensure we pull actual salary
        latest_payslip = Payslip.objects.order_by('-period').first()
        if latest_payslip:
            period = latest_payslip.period
            target_year, target_month = map(int, period.split('-'))
        else:
            latest_attendance = DailyAttendance.objects.order_by('-attendance_date').first()
            if latest_attendance:
                target_year = latest_attendance.attendance_date.year
                target_month = latest_attendance.attendance_date.month
                period = latest_attendance.attendance_date.strftime('%Y-%m')
            else:
                target_year = today.year
                target_month = today.month
                period = today.strftime('%Y-%m')
            
        _, total_days = calendar.monthrange(target_year, target_month)
        
        data = []
        employees = Employee.objects.select_related('entity', 'branch', 'site', 'department', 'designation').all()
        
        # Apply data isolation if needed
        if not user.is_superuser and emp and emp.role not in ['super_admin', 'org_admin']:
            employees = employees.filter(entity=emp.entity)
            
        for e in employees:
            attendances = DailyAttendance.objects.filter(
                employee=e,
                attendance_date__year=target_year,
                attendance_date__month=target_month
            )
            present_days = attendances.filter(attendance_status__in=['Present', 'Late', 'Half Day']).count()
            late_marks = attendances.filter(attendance_status='Late').count()
            
            # Count weekends dynamically
            weekends = 0
            for day in range(1, total_days + 1):
                if calendar.weekday(target_year, target_month, day) >= 5:
                    weekends += 1
            expected_work_days = total_days - weekends
            
            # Try to fetch from LeaveRequest model for more accuracy
            try:
                from leaves.models import LeaveRequest, LeaveBalance
                leave_req = LeaveRequest.objects.filter(
                    employee=e,
                    start_date__year=target_year,
                    start_date__month=target_month,
                    status='Approved'
                ).aggregate(Sum('total_days'))['total_days__sum']
                
                # Prevent leaves from exceeding the month's total days
                leaves_applied_raw = float(leave_req) if leave_req else float(attendances.filter(attendance_status='Leave').count())
                leaves_applied = min(leaves_applied_raw, float(total_days))
                
                leave_bal = LeaveBalance.objects.filter(employee=e, year=target_year).aggregate(Sum('remaining_days'))['remaining_days__sum']
                annual_leave = float(leave_bal) if leave_bal else 0.0
            except Exception:
                leaves_applied_raw = float(attendances.filter(attendance_status='Leave').count())
                leaves_applied = min(leaves_applied_raw, float(total_days))
                annual_leave = 0.0
                
            absent_db = attendances.filter(attendance_status='Absent').count()
            actual_present = attendances.filter(attendance_status__in=['Present', 'Late', 'Half Day']).count()
            
            # Infer absences if the database doesn't have punches for all expected working days
            inferred_absences = max(0, expected_work_days - actual_present - int(leaves_applied))
            absent_days = max(absent_db, inferred_absences)
            
            # Since these are unapproved/unrequested absences, count them as leaves not applied
            leaves_not_applied = absent_days
            
            # Honest tracking of present days from DB
            present_days = actual_present
            
            ot_sum = attendances.aggregate(Sum('overtime_hours'))['overtime_hours__sum']
            overtime = float(ot_sum) if ot_sum else 0.0
            
            # Mathematical safeties to prevent negative days
            net_workdays = max(0, total_days - int(leaves_applied + leaves_not_applied))
            
            loc = late_marks * 0.5 # Basic logic for LOC (0.5 day deduction for late)
            payable_workdays = max(0.0, float(total_days) - float(absent_days) - float(loc))
            
            payslip = Payslip.objects.filter(employee=e, period=period).first()
            if payslip:
                in_hand = float(payslip.net)
            else:
                in_hand = 0.0
            
            data.append({
                "Company": e.entity.name if e.entity else "",
                "Region": e.branch.name if e.branch else "India",
                "Location": e.site.name if e.site else "",
                "Group": e.department.name if e.department else "",
                "Role": e.designation.title if e.designation else "",
                "Employee": f"{e.first_name} {e.last_name}",
                "Total Work Days (A)": total_days,
                "Present Days": present_days,
                "Absent Days": absent_days,
                "No Of Leaves (Applied)": leaves_applied,
                "No Of Leaves (Not Applied)": leaves_not_applied,
                "Net workDays": net_workdays,
                "Payable Work Days": round(payable_workdays, 2),
                "Overtime Hours": overtime,
                "LOC / Time Delay Deduction": loc,
                "Annual Leave": annual_leave,
                "In Hand Salary": in_hand
            })
            
        return Response(data)

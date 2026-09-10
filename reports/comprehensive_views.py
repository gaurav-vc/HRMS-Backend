from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from employees.models import Employee
from payroll.models import Payslip, PayslipLineItem
from attendance.models import DailyAttendance

class ComprehensiveReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        report_type = request.query_params.get('type')
        user = request.user
        emp = getattr(user, 'employee_profile', None)
        
        from authentication.permissions import _get_admin_sites
        admin_sites = _get_admin_sites(user)
        
        # Determine dynamic role access
        has_report_access = False
        if user.is_superuser:
            has_report_access = True
        elif emp and emp.role in ['super_admin', 'org_admin', 'hr', 'manager', 'site_admin']:
            has_report_access = True
        elif admin_sites.exists():
            has_report_access = True
        elif emp and emp.dynamic_role and emp.dynamic_role.permissions.get('reports'):
            has_report_access = True
            
        if not has_report_access:
            return Response({'error': 'Unauthorized'}, status=403)
            
        data = []
        today = timezone.now().date()
        
        # Dynamically find the most recent active data period
        latest_payslip = Payslip.objects.order_by('-period').first()
        target_period = latest_payslip.period if latest_payslip else today.strftime('%Y-%m')
        target_year_str = target_period[:4]
        
        latest_attendance = DailyAttendance.objects.order_by('-attendance_date').first()
        target_attendance_month = latest_attendance.attendance_date.strftime('%Y-%m') if latest_attendance else today.strftime('%Y-%m')
        
        from django.db.models import Q
        emp_q = Q()
        if not user.is_superuser:
            if admin_sites.exists():
                emp_q = Q(site__in=admin_sites) | Q(enrolled_sites__in=admin_sites)
            elif emp:
                if emp.role == 'org_admin':
                    emp_q = Q(entity=emp.entity)
                elif emp.role in ['hr', 'manager']:
                    emp_q = Q(entity=emp.entity)
                else:
                    emp_q = Q(id=emp.id)

        if report_type == 'attrition_analysis':
            active = Employee.objects.filter(emp_q, status='Active').count()
            exits = Employee.objects.filter(emp_q, status__in=['Terminated', 'Resigned']).count()
            data = [{'Status': 'Active', 'Count': active}, {'Status': 'Exited', 'Count': exits}]
            
        elif report_type == 'diversity_report':
            from django.db.models import Count
            diversity = Employee.objects.filter(emp_q, status='Active').values('gender').annotate(count=Count('id'))
            data = [{'Gender': d['gender'], 'Count': d['count']} for d in diversity]
            
        elif report_type == 'new_joiners':
            from datetime import timedelta
            thirty_days_ago = today - timedelta(days=30)
            joiners = Employee.objects.filter(emp_q, doj__gte=thirty_days_ago)
            data = [{'Code': e.code, 'Name': f"{e.first_name} {e.last_name}", 'DOJ': e.doj} for e in joiners]
            
        elif report_type == 'exits':
            exits = Employee.objects.filter(emp_q, status__in=['Terminated', 'Resigned'])
            data = [{'Code': e.code, 'Name': f"{e.first_name} {e.last_name}", 'Status': e.status} for e in exits]
            
        elif report_type == 'monthly_summary':
            month = request.query_params.get('month', target_attendance_month)
            attendances = DailyAttendance.objects.filter(attendance_date__startswith=month)
            if not user.is_superuser and emp:
                attendances = attendances.filter(employee__entity=emp.entity)
            
            summary = {}
            for a in attendances:
                if a.employee.code not in summary:
                    summary[a.employee.code] = {'Name': f"{a.employee.first_name} {a.employee.last_name}", 'Present': 0, 'Absent': 0, 'Late': 0}
                summary[a.employee.code][a.attendance_status] = summary[a.employee.code].get(a.attendance_status, 0) + 1
            data = [{'Code': k, **v} for k, v in summary.items()]
            
        elif report_type == 'overtime':
            attendances = DailyAttendance.objects.filter(overtime_hours__gt=0)
            if not user.is_superuser and emp:
                attendances = attendances.filter(employee__entity=emp.entity)
            data = [{'Date': a.attendance_date, 'Code': a.employee.code, 'Name': f"{a.employee.first_name} {a.employee.last_name}", 'Overtime Hours': a.overtime_hours} for a in attendances]

        elif report_type == 'ctc_distribution':
            slips = Payslip.objects.filter(period=target_period)
            if not user.is_superuser and emp:
                slips = slips.filter(employee__entity=emp.entity)
            data = [{'Code': s.employee.code, 'Name': f"{s.employee.first_name} {s.employee.last_name}", 'Gross': s.gross} for s in slips]
            
        elif report_type == 'cost_by_department':
            slips = Payslip.objects.filter(period=target_period).select_related('employee', 'employee__department')
            if not user.is_superuser and emp:
                slips = slips.filter(employee__entity=emp.entity)
            
            dept_costs = {}
            for s in slips:
                dept = s.employee.department.name if s.employee.department else 'Unknown'
                if dept not in dept_costs:
                    dept_costs[dept] = {'Gross': 0, 'Net': 0}
                dept_costs[dept]['Gross'] += float(s.gross)
                dept_costs[dept]['Net'] += float(s.net)
            data = [{'Department': k, 'Total Gross': v['Gross'], 'Total Net': v['Net']} for k, v in dept_costs.items()]
            
        elif report_type == 'variable_pay':
            lines = PayslipLineItem.objects.filter(rule__name__icontains='variable', payslip__period=target_period)
            if not user.is_superuser and emp:
                lines = lines.filter(payslip__employee__entity=emp.entity)
            data = [{'Code': l.payslip.employee.code, 'Name': f"{l.payslip.employee.first_name} {l.payslip.employee.last_name}", 'Amount': l.amount} for l in lines]
            
        elif report_type == 'bonus_provision':
            lines = PayslipLineItem.objects.filter(rule__name__icontains='bonus', payslip__period=target_period)
            if not user.is_superuser and emp:
                lines = lines.filter(payslip__employee__entity=emp.entity)
            data = [{'Code': l.payslip.employee.code, 'Name': f"{l.payslip.employee.first_name} {l.payslip.employee.last_name}", 'Amount': l.amount} for l in lines]

        elif report_type == 'pf_ecr':
            slips = Payslip.objects.filter(period=target_period)
            if not user.is_superuser and emp:
                slips = slips.filter(employee__entity=emp.entity)
            
            for s in slips:
                pf = 0
                for line in s.lines.all():
                    if 'pf' in line.rule.name.lower() or 'provident' in line.rule.name.lower():
                        pf = line.amount
                data.append({
                    'UAN': s.employee.uan or '',
                    'Name': f"{s.employee.first_name} {s.employee.last_name}",
                    'Gross': s.gross,
                    'EPF Wages': s.gross,
                    'EPS Wages': min(float(s.gross), 15000),
                    'EDLI Wages': min(float(s.gross), 15000),
                    'EPF Contri': pf,
                    'EPS Contri': round(min(float(s.gross), 15000) * 0.0833),
                    'Diff Contri': float(pf) - round(min(float(s.gross), 15000) * 0.0833)
                })
                
        elif report_type == 'esi_return':
            slips = Payslip.objects.filter(period=target_period)
            if not user.is_superuser and emp:
                slips = slips.filter(employee__entity=emp.entity)
            for s in slips:
                esi = 0
                for line in s.lines.all():
                    if 'esi' in line.rule.name.lower():
                        esi = line.amount
                if esi > 0:
                    data.append({
                        'IP Number': getattr(s.employee, 'esi_number', ''),
                        'Name': f"{s.employee.first_name} {s.employee.last_name}",
                        'Worked Days': 30,
                        'Total Wages': s.gross,
                        'Employee Contri': esi
                    })
                    
        elif report_type == 'pt_state_wise':
            slips = Payslip.objects.filter(period=target_period)
            if not user.is_superuser and emp:
                slips = slips.filter(employee__entity=emp.entity)
            pt_dict = {}
            for s in slips:
                state = getattr(s.employee.site, 'state', 'Unknown') if getattr(s.employee, 'site', None) else 'Unknown'
                pt = 0
                for line in s.lines.all():
                    if 'pt' in line.rule.name.lower() or 'professional tax' in line.rule.name.lower():
                        pt = line.amount
                if pt > 0:
                    pt_dict[state] = pt_dict.get(state, 0) + float(pt)
            data = [{'State': k, 'Total PT': v} for k, v in pt_dict.items()]
            
        elif report_type == 'tds_24q':
            slips = Payslip.objects.filter(period=target_period)
            if not user.is_superuser and emp:
                slips = slips.filter(employee__entity=emp.entity)
            for s in slips:
                tds = s.tds
                if tds > 0:
                    data.append({
                        'PAN': s.employee.pan or '',
                        'Name': f"{s.employee.first_name} {s.employee.last_name}",
                        'TDS Amount': tds,
                        'Date of Payment': today.strftime('%Y-%m-%d')
                    })
                    
        elif report_type == 'form_16':
            slips = Payslip.objects.filter(period__startswith=target_year_str)
            if not user.is_superuser and emp:
                slips = slips.filter(employee__entity=emp.entity)
            emp_summary = {}
            for s in slips:
                if s.employee.code not in emp_summary:
                    emp_summary[s.employee.code] = {'Name': f"{s.employee.first_name} {s.employee.last_name}", 'Gross': 0, 'TDS': 0}
                emp_summary[s.employee.code]['Gross'] += float(s.gross)
                emp_summary[s.employee.code]['TDS'] += float(s.tds)
            data = [{'Code': k, 'Name': v['Name'], 'Annual Gross': v['Gross'], 'Total TDS': v['TDS']} for k, v in emp_summary.items()]
            
        else:
            return Response({'error': 'Unknown report type'}, status=400)
            
        return Response(data)

from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta
from employees.models import Employee
from organisation.models import Entity, Site
from admin_org.models import Organization, Invoice
from leaves.models import LeaveRequest, LeaveBalance
from attendance.models import DailyAttendance, PunchLog, RegularizationRequest
from payroll.models import PayrollRun, Loan, Reimbursement
from decimal import Decimal
from django.db.models import Count, Sum
from datetime import date

class DashboardStatsAPIView(APIView):
    def get(self, request):
        user = request.user
        
        # Strict security boundary: Superuser only sees super admin data, NO site data
        if user.is_superuser:
            total_revenue_query = Invoice.objects.aggregate(Sum('amount'))['amount__sum']
            total_revenue = float(total_revenue_query) if total_revenue_query else 0.0

            super_admin_stats = {
                "totalRevenue": total_revenue,
                "activeSites": Site.objects.filter(status='Active', is_sub_site=False).count(),
                "totalCompany": Organization.objects.count(),
                "moduleWiseRevenue": []
            }
            try:
                top_orgs = list(Organization.objects.annotate(site_count=Count('sites')).order_by('-site_count')[:3])
                top_org_names = [org.name for org in top_orgs]
                
                today_date = timezone.now().date()
                months = []
                for i in range(6, -1, -1):
                    m = today_date.month - i
                    y = today_date.year
                    while m <= 0:
                        m += 12
                        y -= 1
                    months.append(date(y, m, 1))
                
                company_wise_data = []
                for m in months:
                    month_name = m.strftime('%b')
                    data_point = {"name": month_name}
                    for org in top_orgs:
                        count = Site.objects.filter(organization=org, created_at__date__lte=date(m.year, m.month, 28), is_sub_site=False).count()
                        data_point[org.name] = count
                    company_wise_data.append(data_point)
                
                module_wise_data = []
                for m in months:
                    month_name = m.strftime('%b')
                    count = Site.objects.filter(created_at__date__lte=date(m.year, m.month, 28), is_sub_site=False).count()
                    module_wise_data.append({"name": month_name, "site": count})
                    
                super_admin_stats["companyWiseSite"] = company_wise_data
                super_admin_stats["moduleWiseSite"] = module_wise_data
                super_admin_stats["topOrgs"] = top_org_names
            except Exception as e:
                super_admin_stats["companyWiseSite"] = []
                super_admin_stats["moduleWiseSite"] = []
                super_admin_stats["topOrgs"] = []

            return Response({
                "super_admin": super_admin_stats
            })

        today = timezone.localdate()
        can_view_confidential = False
        emp = getattr(user, 'employee_profile', None)
        if emp and emp.dynamic_role and emp.dynamic_role.permissions and emp.dynamic_role.permissions.get('can_view_confidential_payroll') in [True, 'true', 'True', 1, '1']:
            can_view_confidential = True
        
        from authentication.permissions import isolate_queryset

        # Self-heal unassigned site/entity for employees in the user's organization
        # Resolves orphan records where an employee was created without a site assignment
        if emp and emp.organization_id:
            unassigned_emps = Employee.objects.filter(organization_id=emp.organization_id, site__isnull=True)
            if unassigned_emps.exists():
                primary_site = emp.site or Site.objects.filter(organization_id=emp.organization_id).first()
                if primary_site:
                    unassigned_emps.update(site=primary_site)
            # Inherit missing entity from primary site's branch entity
            site_to_use = emp.site or Site.objects.filter(organization_id=emp.organization_id).first()
            if site_to_use and site_to_use.branch and site_to_use.branch.entity_id:
                Employee.objects.filter(organization_id=emp.organization_id, entity__isnull=True).update(entity=site_to_use.branch.entity)
        
        # 1. Headcount & Entities
        employees = isolate_queryset(Employee.objects.all(), user)
        entities = isolate_queryset(Entity.objects.all(), user)
        
        total_headcount = employees.filter(status='Active').count()
        
        headcount_by_entity = []
        for e in entities:
            headcount_by_entity.append({
                "name": e.code or e.name,
                "value": employees.filter(entity=e, status='Active').count()
            })
            
        # 2. Payroll
        runs = isolate_queryset(PayrollRun.objects.all(), user).order_by('period')
        recent_runs = []
        for r in runs.order_by('-period')[:5]:
            recent_runs.append({
                "id": r.id,
                "period": r.period,
                "employees": employees.filter(entity=r.entity).count(), # rough estimate
                "net": float(sum(p.net for p in r.payslip_set.all()) if (r.payslip_set.exists() and can_view_confidential) else 0),
                "status": r.status
            })
            
        last_run_net = recent_runs[0]['net'] if recent_runs else 0
        
        monthly_trend = []
        for r in runs.order_by('-period')[:6]:
            try:
                m = r.period.split('-')[1]
                if can_view_confidential:
                    net_total = float(sum(p.net for p in r.payslip_set.all()))
                    gross_total = float(sum(p.gross for p in r.payslip_set.all()))
                else:
                    net_total = 0
                    gross_total = 0
                monthly_trend.append({"month": m, "net": net_total / 100000, "gross": gross_total / 100000}) # In Lakhs
            except:
                pass
        monthly_trend.reverse()
        
        # 3. Attendance
        present_today = isolate_queryset(DailyAttendance.objects.all(), user).filter(attendance_date=today, attendance_status='Present').count()
        
        # Attendance Modes
        # rough estimate from punch logs today
        punches_today = isolate_queryset(PunchLog.objects.all(), user).filter(punch_time__date=today)
        qr_count = punches_today.filter(source='QR').count()
        face_count = punches_today.filter(source='FACE').count()
        gps_count = punches_today.filter(source='GPS').count()
            
        # 4. Leaves & Exceptions
        pending_leaves = isolate_queryset(LeaveRequest.objects.all(), user).filter(status='Pending')
        
        exceptions = []
        # Add some geofence exceptions if gps > 150m (assuming we store distance, wait we have lat/lng but not distance in model, so fake it if needed)
        
        for l in pending_leaves[:2]:
            exceptions.append({
                "kind": "Leave",
                "who": f"{l.employee.first_name} {l.employee.last_name}",
                "detail": f"{l.leave_type.name} {l.total_days}d",
                "tone": "info"
            })
            
        pending_regs = isolate_queryset(RegularizationRequest.objects.all(), user).filter(status='Pending')
        for r in pending_regs[:2]:
            exceptions.append({
                "kind": "Regularization",
                "who": f"{r.employee.first_name} {r.employee.last_name}",
                "detail": "Awaiting review",
                "tone": "info"
            })
            
        pending_leave_list = []
        for l in pending_leaves[:5]:
            pending_leave_list.append({
                "id": l.id,
                "empName": f"{l.employee.first_name} {l.employee.last_name}",
                "type": l.leave_type.name,
                "days": float(l.total_days),
                "from": str(l.start_date),
                "status": l.status
            })
            
        # Dynamic deltas and cycle periods
        payroll_cycle_month = today.strftime('%B')
        if recent_runs and recent_runs[0].get('period'):
            try:
                parts = recent_runs[0]['period'].split('-')
                if len(parts) >= 2:
                    payroll_cycle_month = date(int(parts[0]), int(parts[1]), 1).strftime('%B')
            except Exception:
                pass
                
        payroll_growth = "+0.0%"
        if len(recent_runs) >= 2 and recent_runs[1].get('net', 0) > 0:
            diff = ((recent_runs[0]['net'] - recent_runs[1]['net']) / recent_runs[1]['net']) * 100
            payroll_growth = f"{'+' if diff >= 0 else ''}{diff:.1f}%"
            
        new_hires_count = employees.filter(status='Active', doj__gte=today - timedelta(days=30)).count()
        headcount_delta = f"+{new_hires_count} new this month" if new_hires_count > 0 else "Stable vs last period"
        attendance_rate = round((present_today / total_headcount) * 100, 1) if total_headcount > 0 else 0
        attendance_delta = f"{attendance_rate}% turnout"
        approvals_delta = f"{pending_leaves.count()} leaves, {pending_regs.count()} reg"

        super_admin_stats = {}

        payload = {
            "super_admin": super_admin_stats,
            "executive": {
                "totalHeadcount": total_headcount,
                "presentToday": present_today,
                "pendingLeaves": pending_leaves.count(),
                "pendingRegs": pending_regs.count(),
                "totalPendingApprovals": pending_leaves.count() + pending_regs.count(),
                "lastRunNet": last_run_net,
                "entitiesCount": entities.count(),
                "payrollTrend": monthly_trend,
                "headcountByEntity": headcount_by_entity,
                "pendingLeaveList": pending_leave_list,
                "recentRuns": recent_runs,
                "attendanceModes": { "qr": qr_count, "face": face_count, "gps": gps_count },
                "exceptionAlerts": exceptions,
                "payrollCycleMonth": payroll_cycle_month,
                "payrollGrowth": payroll_growth,
                "headcountDelta": headcount_delta,
                "attendanceDelta": attendance_delta,
                "approvalsDelta": approvals_delta,
            },
            "payroll": {
                "activeCycle": recent_runs[0]['period'] if recent_runs else today.strftime("%Y-%m"),
                "employeesInCycle": total_headcount,
                "activeLoans": isolate_queryset(Loan.objects.all(), user).filter(status='Active').count(),
                "pendingReimbursements": isolate_queryset(Reimbursement.objects.all(), user).filter(status='Pending').count(),
                "recentRuns": recent_runs
            },
            "manager": {
                "myTeamCount": total_headcount,
                "onLeaveToday": isolate_queryset(LeaveRequest.objects.all(), user).filter(status='Approved', start_date__lte=today, end_date__gte=today).count(),
                "pendingApprovals": pending_leaves.count() + pending_regs.count(),
                "teamRoster": [{"id": e.id, "firstName": e.first_name, "lastName": e.last_name, "code": e.code} for e in employees[:8]],
                "todayAttendance": [{"id": a.id, "empName": f"{a.employee.first_name} {a.employee.last_name}", "checkIn": a.first_check_in.strftime("%H:%M") if a.first_check_in else "N/A", "status": a.attendance_status} for a in isolate_queryset(DailyAttendance.objects.all(), user).filter(attendance_date=today)[:6]]
            },
            "employee": {
                "presentThisMonth": DailyAttendance.objects.filter(employee=emp, attendance_date__month=today.month, attendance_status='Present').count() if emp else 0,
                "workingDays": ((today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day,
                "leaveBalance": float(LeaveBalance.objects.filter(employee=emp).aggregate(total=Sum('remaining_days'))['total'] or 0) if emp else 0,
                "lastNetPay": last_run_net,
                "recentAttendance": [{"id": a.id, "date": str(a.attendance_date), "checkIn": a.first_check_in.strftime("%H:%M") if a.first_check_in else "N/A", "checkOut": a.last_check_out.strftime("%H:%M") if a.last_check_out else "N/A"} for a in DailyAttendance.objects.filter(employee=emp).order_by('-attendance_date')[:5]] if emp else [],
                "myLeaveRequests": [{"id": l.id, "type": l.leave_type.name, "from": str(l.start_date), "status": l.status} for l in LeaveRequest.objects.filter(employee=emp).order_by('-created_at')[:5]] if emp else [],
                "siteQrEnabled": emp.site.qr_enabled if emp and hasattr(emp, 'site') and emp.site else True,
                "siteFaceEnabled": emp.site.face_enabled if emp and hasattr(emp, 'site') and emp.site else True,
            }
        }
        
        return Response(payload)

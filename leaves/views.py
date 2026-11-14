from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.utils import timezone
from .models import LeaveType, LeaveBalance, LeaveRequest, Holiday, LeavePolicyConfiguration
from .serializers import LeaveTypeSerializer, LeaveBalanceSerializer, LeaveRequestSerializer, HolidaySerializer, LeavePolicyConfigurationSerializer
from decimal import Decimal
from datetime import timedelta, date
from django.db.models import Q
import threading
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from authentication.permissions import DataIsolationMixin

def send_leave_email_async(emp_email, emp_name, status, start_date, end_date, total_days, reason, manager_comments):
    if not emp_email:
        return
        
    def _send():
        subject = f'Your Leave Request has been {status}'
        
        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background-color: #0b1b3d; padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
                    <h2 style="color: white; margin: 0;">Leave Request Update</h2>
                </div>
                <div style="padding: 30px; border: 1px solid #ddd; border-top: none; border-radius: 0 0 8px 8px;">
                    <p style="font-size: 16px;">Hello <strong>{emp_name}</strong>,</p>
                    <p style="font-size: 15px; line-height: 1.5;">Your leave request has been <strong>{status}</strong>. Please find the details below:</p>
                    
                    <div style="background-color: #f8fafc; padding: 20px; border-radius: 6px; margin: 25px 0;">
                        <p style="margin: 0 0 10px 0;"><strong>Status:</strong> {status}</p>
                        <p style="margin: 0 0 10px 0;"><strong>Dates:</strong> {start_date} to {end_date}</p>
                        <p style="margin: 0 0 10px 0;"><strong>Total Days:</strong> {total_days}</p>
                        <p style="margin: 0 0 10px 0;"><strong>Reason:</strong> {reason}</p>
                        <p style="margin: 0;"><strong>Manager Comments:</strong> {manager_comments}</p>
                    </div>
                    
                    <br/>
                    <p style="font-size: 14px; color: #666; margin: 0;">Best Regards,</p>
                    <p style="font-size: 14px; color: #666; font-weight: bold; margin: 5px 0 0 0;">HRMS Administration</p>
                </div>
            </body>
        </html>
        """
        
        text_content = strip_tags(html_content)
        
        try:
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None) or 'HRMS Administration <noreply@hrms.local>'
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email,
                to=[emp_email]
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=True)
            print(f"Leave status email successfully dispatched to {emp_email}")
        except Exception as e:
            print(f"Failed to send leave status email to {emp_email}: {str(e)}")
            
    threading.Thread(target=_send).start()

def calculate_working_days(start_date, end_date, site_id=None):
    from .models import LeavePolicyConfiguration
    from attendance.models import Holiday
    config = LeavePolicyConfiguration.get_settings()
    is_saturday_working = config.is_saturday_working

    # Fetch holidays between dates
    holidays_query = Holiday.objects.filter(date__gte=start_date, date__lte=end_date)
    if site_id:
        holidays_query = holidays_query.filter(Q(site_id=site_id) | Q(site__isnull=True))
    else:
        holidays_query = holidays_query.filter(site__isnull=True)
        
    holiday_dates = set(holidays_query.values_list('date', flat=True))

    days = 0
    current_date = start_date
    while current_date <= end_date:
        weekday = current_date.weekday()
        is_working_day = (weekday < 5) or (weekday == 5 and is_saturday_working)
        
        if is_working_day and current_date not in holiday_dates:
            days += 1
        current_date += timedelta(days=1)
    return Decimal(days)

class LeavePolicyConfigAPIView(APIView):
    rbac_module = 'Leave Policies'
    def get(self, request):
        import sys
        config = LeavePolicyConfiguration.get_settings()
        serializer = LeavePolicyConfigurationSerializer(config)
        print("==== GET RESPONSE DATA ====", serializer.data, file=sys.stderr)
        return Response(serializer.data)
        
    def put(self, request):
        import sys
        config = LeavePolicyConfiguration.get_settings()
        serializer = LeavePolicyConfigurationSerializer(config, data=request.data)
        if serializer.is_valid():
            serializer.save()
            print("==== PUT RESPONSE DATA ====", serializer.data, file=sys.stderr)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LeaveTypeViewSet(DataIsolationMixin, viewsets.ReadOnlyModelViewSet):
    rbac_module = 'Leave Policies'
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer

    def get_queryset(self):
        try:
            qs = super().get_queryset()
            if not qs.exists():
                LeaveType.objects.create(name="Annual Leave", code="AL", annual_entitlement=12.0)
                LeaveType.objects.create(name="Sick Leave", code="SL", annual_entitlement=5.0)
                LeaveType.objects.create(name="Loss of Pay", code="LOP", annual_entitlement=0.0)
                qs = super().get_queryset()
            return qs
        except Exception as e:
            import traceback
            print("LeaveType Query Error:", traceback.format_exc())
            return super().get_queryset()

class LeaveBalanceViewSet(DataIsolationMixin, viewsets.ReadOnlyModelViewSet):
    rbac_module = 'Leave Balances'
    serializer_class = LeaveBalanceSerializer

    def get_queryset(self):
        qs = LeaveBalance.objects.all()
        from .models import LeavePolicyConfiguration, LeaveType
        from datetime import date
        from decimal import Decimal
        import calendar
        from attendance.models import DailyAttendance
        from .models import LeaveRequest

        user = self.request.user
        
        def calculate_earned_al(employee, year):
            earned = Decimal('0.00')
            current_month = date.today().month
            current_year = date.today().year
            
            eval_months = 12 if year != current_year else current_month
                
            for m in range(1, eval_months + 1):
                start_date = date(year, m, 1)
                last_day = calendar.monthrange(year, m)[1]
                end_date = date(year, m, last_day)
                
                if employee.doj and employee.doj > end_date:
                    continue
                
                # Check for approved leaves (holiday taken)
                leaves_taken = LeaveRequest.objects.filter(
                    employee=employee,
                    status='Approved',
                    start_date__lte=end_date,
                    end_date__gte=start_date
                ).exists()
                
                if leaves_taken:
                    continue
                    
                # Check for intentional absences if required
                leave_config = LeavePolicyConfiguration.get_settings()
                if leave_config.require_full_attendance_for_al:
                    intentional_absences = DailyAttendance.objects.filter(
                        employee=employee,
                        attendance_date__range=[start_date, end_date],
                        attendance_status='Absent'
                    ).exists()
                    
                    if intentional_absences:
                        continue
                    
                earned += Decimal('1.00')
                
            return earned

        if hasattr(user, 'employee_profile') and user.employee_profile:
            emp = user.employee_profile
            year = date.today().year
            if not LeaveBalance.objects.filter(employee=emp, year=year).exists():
                leave_types = LeaveType.objects.all()
                for lt in leave_types:
                    entitlement = lt.annual_entitlement
                    if lt.code == 'AL':
                        entitlement = calculate_earned_al(emp, year)
                    LeaveBalance.objects.create(
                        employee=emp,
                        leave_type=lt,
                        year=year,
                        allocated_days=entitlement,
                        used_days=0,
                        remaining_days=entitlement
                    )

        if not (user.is_superuser or getattr(user, 'role', '') in ['HR Admin', 'Site Admin']):
            if hasattr(user, 'employee_profile'):
                qs = qs.filter(employee=user.employee_profile)

        try:
            for balance in qs:
                needs_save = False
                if balance.leave_type.code == 'AL' and balance.employee:
                    new_entitlement = calculate_earned_al(balance.employee, balance.year)
                    if balance.allocated_days != new_entitlement:
                        balance.allocated_days = new_entitlement
                        balance.remaining_days = new_entitlement - balance.used_days
                        needs_save = True
                elif balance.leave_type.code == 'LOP' and balance.allocated_days != Decimal('0.00'):
                    balance.allocated_days = Decimal('0.00')
                    balance.remaining_days = Decimal('0.00') - balance.used_days
                    needs_save = True
                    
                if needs_save:
                    balance.save()
        except Exception as e:
            import traceback
            print("Earned AL calc error:", e)
            
        return qs



class LeaveRequestViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Leave Requests'
    serializer_class = LeaveRequestSerializer

    def get_queryset(self):
        qs = LeaveRequest.objects.all().order_by('-created_at')
        
        mode = getattr(self.request, 'query_params', getattr(self.request, 'GET', {})).get('mode')
        user = self.request.user
        employee = getattr(user, 'employee_profile', None)

        from authentication.permissions import isolate_queryset
        qs = isolate_queryset(qs, user)

        if mode == 'inbox' and employee:
            from django.db.models import Q
            from authentication.permissions import _get_tenant_scope
            # The current employee should ONLY see leave requests where THEY are the designated reporting person:
            # 1. Directly: req.employee.manager == employee
            # 2. Or via Settings: req.employee.dynamic_role.reporting_to == employee.dynamic_role
            # 3. Or if Site Admin/Admin of that site, for employees with no manager and no reporting_to
            q = Q(employee__manager=employee)
            if employee.dynamic_role_id:
                q |= Q(employee__dynamic_role__reporting_to_id=employee.dynamic_role_id)
            
            if employee.role in ('site_admin', 'admin') or getattr(employee.dynamic_role, 'code', None) == 'SITE_ADMIN':
                q |= Q(employee__manager__isnull=True, employee__dynamic_role__reporting_to__isnull=True)

            all_tenant_site_ids, _, _, _ = _get_tenant_scope(user)
            inbox_qs = LeaveRequest.objects.all().order_by('-created_at')
            if all_tenant_site_ids:
                inbox_qs = inbox_qs.filter(Q(employee__site_id__in=all_tenant_site_ids) | Q(employee__enrolled_sites__id__in=all_tenant_site_ids))
            
            return inbox_qs.filter(q).exclude(employee=employee).distinct().select_related(
                'employee',
                'employee__designation',
                'employee__department',
                'employee__entity',
                'employee__site',
                'leave_type',
                'site',
                'entity',
                'organization',
            )
        elif mode == 'my_leaves':
            # Show only their own leaves
            if employee:
                return qs.filter(employee=employee).select_related(
                    'employee',
                    'employee__designation',
                    'employee__department',
                    'employee__entity',
                    'employee__site',
                    'leave_type',
                    'site',
                    'entity',
                    'organization',
                )
            else:
                return qs.none()
            
        return qs.select_related(
            'employee',
            'employee__designation',
            'employee__department',
            'employee__entity',
            'employee__site',
            'leave_type',
            'site',
            'entity',
            'organization',
        )

    def perform_create(self, serializer):
        from django.db import transaction
        from rest_framework.exceptions import ValidationError
        
        employee = serializer.validated_data.get('employee')
        if not employee and hasattr(self.request.user, 'employee_profile'):
            employee = self.request.user.employee_profile
            serializer.validated_data['employee'] = employee

        if not employee:
            raise ValidationError({"detail": "Employee profile not found for this user."})

        start_date = serializer.validated_data.get('start_date')
        end_date = serializer.validated_data.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise ValidationError({"detail": "Start date must be before or equal to end date."})

        # Overlapping leave check
        overlap = LeaveRequest.objects.filter(
            employee=employee,
            status__in=['Pending', 'Approved'],
            start_date__lte=end_date,
            end_date__gte=start_date
        ).exists()
        if overlap:
            raise ValidationError({"detail": "A leave request already exists covering this date range."})

        # Calculate total days
        total_days_input = self.request.data.get('total_days') or self.request.data.get('totalDays')
        if total_days_input:
            total_days = Decimal(str(total_days_input))
        else:
            site_id = employee.site_id if employee and employee.site else None
            total_days = calculate_working_days(start_date, end_date, site_id=site_id)

        if total_days <= Decimal('0'):
            raise ValidationError({"detail": "Leave duration must be greater than 0 working days."})

        leave_type = serializer.validated_data.get('leave_type')
        year = start_date.year

        with transaction.atomic():
            balance = LeaveBalance.objects.select_for_update().filter(
                employee=employee, leave_type=leave_type, year=year
            ).first()

            if not balance:
                entitlement = leave_type.annual_entitlement
                config = LeavePolicyConfiguration.get_settings()
                if entitlement == config.standard_annual_leaves and employee and employee.doj:
                    years_of_service = (date.today() - employee.doj).days / 365.25
                    if years_of_service >= config.tenured_years_threshold:
                        entitlement = config.tenured_annual_leaves
                    else:
                        entitlement = config.standard_annual_leaves

                balance = LeaveBalance.objects.create(
                    employee=employee,
                    leave_type=leave_type,
                    year=year,
                    allocated_days=entitlement,
                    used_days=0,
                    remaining_days=entitlement
                )

            is_unpaid = (leave_type.annual_entitlement == 0)
            if not is_unpaid and balance.remaining_days < total_days:
                raise ValidationError({"detail": f"Insufficient leave balance. You have {balance.remaining_days} days remaining."})

            config = LeavePolicyConfiguration.get_settings()
            salary_deduction_days = Decimal('0.0')

            if total_days > config.max_consecutive_leaves and start_date.month != config.exception_month:
                salary_deduction_days = total_days - Decimal(config.max_consecutive_leaves)

            entity = getattr(employee, 'entity', None)
            organization = getattr(employee, 'organization', None)
            site = getattr(employee, 'site', None)
            serializer.save(
                employee=employee,
                entity=entity,
                organization=organization,
                site=site,
                total_days=total_days,
                salary_deduction_days=salary_deduction_days,
                status='Pending'
            )

    @action(detail=True, methods=['patch', 'post'])
    def approve(self, request, pk=None):
        from authentication.permissions import user_can_approve
        from django.db import transaction
        if not user_can_approve(request.user, module='Leave Requests'):
            return Response({"detail": "Permission denied. You do not have permission to approve leave requests."}, status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            leave_req = LeaveRequest.objects.select_for_update().filter(pk=pk).first()
            if not leave_req:
                return Response({"detail": "Leave request not found."}, status=status.HTTP_404_NOT_FOUND)

            if leave_req.status != 'Pending':
                return Response({"detail": "Only pending requests can be approved."}, status=status.HTTP_400_BAD_REQUEST)

            year = leave_req.start_date.year
            balance = LeaveBalance.objects.select_for_update().filter(
                employee=leave_req.employee, 
                leave_type=leave_req.leave_type, 
                year=year
            ).first()

            paid_days = leave_req.total_days - leave_req.salary_deduction_days
            is_unpaid = (leave_req.leave_type.annual_entitlement == 0)

            if not is_unpaid and (not balance or balance.remaining_days < paid_days):
                return Response({"detail": "Insufficient leave balance to approve this request."}, status=status.HTTP_400_BAD_REQUEST)

            if balance and not is_unpaid:
                balance.used_days += paid_days
                balance.remaining_days -= paid_days
                balance.save()

            leave_req.status = 'Approved'
            leave_req.manager_comments = request.data.get('manager_comments', '')
            leave_req.approved_at = timezone.now()
            user_display = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
            leave_req.approved_by = user_display
            leave_req.save()

        if leave_req.employee and leave_req.employee.email:
            send_leave_email_async(
                emp_email=leave_req.employee.email,
                emp_name=f"{leave_req.employee.first_name} {leave_req.employee.last_name}".strip(),
                status="Approved",
                start_date=leave_req.start_date.strftime("%Y-%m-%d"),
                end_date=leave_req.end_date.strftime("%Y-%m-%d"),
                total_days=leave_req.total_days,
                reason=leave_req.reason,
                manager_comments=leave_req.manager_comments
            )

        return Response(self.get_serializer(leave_req).data)

    @action(detail=True, methods=['patch', 'post'])
    def reject(self, request, pk=None):
        from authentication.permissions import user_can_approve
        from django.db import transaction
        if not user_can_approve(request.user, module='Leave Requests'):
            return Response({"detail": "Permission denied. You do not have permission to reject leave requests."}, status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            leave_req = LeaveRequest.objects.select_for_update().filter(pk=pk).first()
            if not leave_req:
                return Response({"detail": "Leave request not found."}, status=status.HTTP_404_NOT_FOUND)

            if leave_req.status != 'Pending':
                return Response({"detail": "Only pending requests can be rejected."}, status=status.HTTP_400_BAD_REQUEST)

            leave_req.status = 'Rejected'
            leave_req.manager_comments = request.data.get('manager_comments', '')
            leave_req.save()

        if leave_req.employee and leave_req.employee.email:
            send_leave_email_async(
                emp_email=leave_req.employee.email,
                emp_name=f"{leave_req.employee.first_name} {leave_req.employee.last_name}".strip(),
                status="Rejected",
                start_date=leave_req.start_date.strftime("%Y-%m-%d"),
                end_date=leave_req.end_date.strftime("%Y-%m-%d"),
                total_days=leave_req.total_days,
                reason=leave_req.reason,
                manager_comments=leave_req.manager_comments
            )

        return Response(self.get_serializer(leave_req).data)

    @action(detail=True, methods=['patch', 'post'])
    def cancel(self, request, pk=None):
        from django.db import transaction
        leave_req = self.get_object()
        
        emp = getattr(request.user, 'employee_profile', None)
        can_cancel = bool(
            request.user.is_superuser or
            (emp and (emp == leave_req.employee or emp.role in ('super_admin', 'org_admin', 'admin', 'hr')))
        )
        if not can_cancel:
            return Response({"detail": "You do not have permission to cancel this leave request."}, status=status.HTTP_403_FORBIDDEN)

        if leave_req.status in ['Cancelled', 'Rejected']:
            return Response({"detail": f"Leave request is already {leave_req.status.lower()}."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            leave_req = LeaveRequest.objects.select_for_update().get(pk=pk)
            
            # If it was Approved, refund the deducted balance atomically
            if leave_req.status == 'Approved':
                year = leave_req.start_date.year
                balance = LeaveBalance.objects.select_for_update().filter(
                    employee=leave_req.employee,
                    leave_type=leave_req.leave_type,
                    year=year
                ).first()
                if balance:
                    paid_days = leave_req.total_days - leave_req.salary_deduction_days
                    balance.used_days = max(Decimal('0'), balance.used_days - paid_days)
                    balance.remaining_days = balance.allocated_days - balance.used_days
                    balance.save()

            leave_req.status = 'Cancelled'
            leave_req.manager_comments = request.data.get('manager_comments', leave_req.manager_comments)
            leave_req.save()

        return Response(self.get_serializer(leave_req).data)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        qs = self.get_queryset()
        pending = qs.filter(status='Pending').count()
        approved = qs.filter(status='Approved').count()
        rejected = qs.filter(status='Rejected').count()
        return Response({
            "pending": pending,
            "approved": approved,
            "rejected": rejected
        })

class HolidayViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    queryset = Holiday.objects.all()
    serializer_class = HolidaySerializer

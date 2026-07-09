from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.utils import timezone
from .models import LeaveType, LeaveBalance, LeaveRequest, Holiday, LeavePolicyConfiguration
from .serializers import LeaveTypeSerializer, LeaveBalanceSerializer, LeaveRequestSerializer, HolidaySerializer, LeavePolicyConfigurationSerializer
from decimal import Decimal
from datetime import timedelta
from django.db.models import Q

def calculate_working_days(start_date, end_date, site_id=None):
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
        if current_date.weekday() < 5 and current_date not in holiday_dates:  # Monday to Friday and not a holiday
            days += 1
        current_date += timedelta(days=1)
    return Decimal(days)

class LeavePolicyConfigAPIView(APIView):
    def get(self, request):
        config = LeavePolicyConfiguration.get_settings()
        serializer = LeavePolicyConfigurationSerializer(config)
        return Response(serializer.data)
        
    def put(self, request):
        config = LeavePolicyConfiguration.get_settings()
        serializer = LeavePolicyConfigurationSerializer(config, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LeaveTypeViewSet(viewsets.ReadOnlyModelViewSet):
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
            trace = traceback.format_exc()
            with open(r"C:\Users\MC VIP\.gemini\antigravity-ide\brain\e67bb007-f83e-496e-af2d-2e9dcae7f046\scratch\error_log_types.txt", "w") as f:
                f.write(trace)
            return super().get_queryset()

class LeaveBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LeaveBalanceSerializer

    def get_queryset(self):
        qs = LeaveBalance.objects.all()
        from .models import LeavePolicyConfiguration
        from datetime import date
        from decimal import Decimal
        
        try:
            config = LeavePolicyConfiguration.get_settings()
            for balance in qs:
                needs_save = False
                entitlement = balance.leave_type.annual_entitlement
                if balance.leave_type.code == 'AL' and balance.employee and balance.employee.doj:
                    years = (date.today() - balance.employee.doj).days / 365.25
                    if years >= config.tenured_years_threshold:
                        entitlement = config.tenured_annual_leaves
                    else:
                        entitlement = config.standard_annual_leaves
                        
                if balance.allocated_days == Decimal('20.00') and entitlement != Decimal('20.00'):
                    balance.allocated_days = entitlement
                    balance.remaining_days = entitlement - balance.used_days
                    needs_save = True
                elif balance.leave_type.code == 'LOP' and balance.allocated_days != Decimal('0.00'):
                    balance.allocated_days = Decimal('0.00')
                    balance.remaining_days = Decimal('0.00') - balance.used_days
                    needs_save = True
                    
                if needs_save:
                    balance.save()
        except Exception:
            pass
            
        return qs

from authentication.permissions import DataIsolationMixin

class LeaveRequestViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    serializer_class = LeaveRequestSerializer

    def get_queryset(self):
        qs = LeaveRequest.objects.all().order_by('-created_at')
        
        mode = self.request.query_params.get('mode')
        user = self.request.user
        employee = getattr(user, 'employee_profile', None)

        from authentication.permissions import isolate_queryset
        qs = isolate_queryset(qs, user)

        if mode == 'inbox' and employee:
            # Show all leaves they have access to, EXCEPT their own
            return qs.exclude(employee=employee)
        elif mode == 'my_leaves' and employee:
            # Show only their own leaves
            return qs.filter(employee=employee)
            
        return qs

    def perform_create(self, serializer):
        try:
            employee = serializer.validated_data.get('employee')
            if not employee and hasattr(self.request.user, 'employee_profile'):
                employee = self.request.user.employee_profile
                serializer.validated_data['employee'] = employee
    
            if not employee:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"detail": "Employee profile not found for this user."})
    
            # Calculate total days
            start_date = serializer.validated_data.get('start_date')
            end_date = serializer.validated_data.get('end_date')
            # If the frontend passes a custom total_days (like 0.5 for half day), we can use it, else calculate
            total_days_input = self.request.data.get('total_days')
            if total_days_input:  # Checks for None and empty string ''
                total_days = Decimal(str(total_days_input))
            else:
                employee = serializer.validated_data.get('employee')
                site_id = employee.site_id if employee and employee.site else None
                total_days = calculate_working_days(start_date, end_date, site_id=site_id)
    
            # Balance check
            employee = serializer.validated_data.get('employee')
            leave_type = serializer.validated_data.get('leave_type')
            year = start_date.year
    
            from rest_framework.exceptions import ValidationError
            balance = LeaveBalance.objects.filter(employee=employee, leave_type=leave_type, year=year).first()
            if not balance:
                # Auto-create balance for testing/convenience
                entitlement = leave_type.annual_entitlement
                if leave_type.code == 'AL' and employee and employee.doj:
                    from datetime import date
                    from decimal import Decimal
                    config = LeavePolicyConfiguration.get_settings()
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
    
            if balance.remaining_days < total_days:
                raise ValidationError({"detail": "Insufficient leave balance."})
    
            # Apply Leave Policy Restrictions
            config = LeavePolicyConfiguration.get_settings()
            salary_deduction_days = Decimal('0.0')
    
            if total_days > config.max_consecutive_leaves:
                # Check if it falls within the exception month
                if start_date.month != config.exception_month:
                    salary_deduction_days = total_days - Decimal(config.max_consecutive_leaves)
                    # Ensure they don't use up remaining_days for unpaid leave
                    # (The unpaid days shouldn't deduct from paid balance, but for now we just record it)
                    # Actually, if total_days is 8 and max is 3, 5 are unpaid. 
                    # So we only deduct 3 from their actual paid balance in the approve step.
                    
            # Optional: verify if tenured or not
            if employee and employee.doj:
                doj = employee.doj
                try:
                    five_years_later = doj.replace(year=doj.year + config.tenured_years_threshold)
                except ValueError:
                    five_years_later = doj.replace(year=doj.year + config.tenured_years_threshold, day=28)
                
                is_tenured = (start_date.year > five_years_later.year) or \
                             (start_date.year == five_years_later.year and start_date.month > five_years_later.month)
                # You can use `is_tenured` to automatically upgrade their leave allocations here if desired.
    
            serializer.save(employee=employee, total_days=total_days, salary_deduction_days=salary_deduction_days, status='Pending')
        except Exception as e:
            import traceback
            trace = traceback.format_exc()
            from rest_framework.exceptions import APIException
            class CustomAPIException(APIException):
                status_code = 400
                default_detail = trace
            raise CustomAPIException(trace)

    @action(detail=True, methods=['patch'])
    def approve(self, request, pk=None):
        leave_req = self.get_object()
        if leave_req.status != 'Pending':
            return Response({"detail": "Only pending requests can be approved."}, status=status.HTTP_400_BAD_REQUEST)

        # Deduct balance only after approval
        year = leave_req.start_date.year
        balance = LeaveBalance.objects.filter(
            employee=leave_req.employee, 
            leave_type=leave_req.leave_type, 
            year=year
        ).first()

        if not balance or balance.remaining_days < (leave_req.total_days - leave_req.salary_deduction_days):
            return Response({"detail": "Insufficient leave balance to approve this request."}, status=status.HTTP_400_BAD_REQUEST)

        # Only deduct the paid portion
        paid_days = leave_req.total_days - leave_req.salary_deduction_days
        balance.used_days += paid_days
        balance.remaining_days -= paid_days
        balance.save()

        leave_req.status = 'Approved'
        leave_req.manager_comments = request.data.get('manager_comments', '')
        leave_req.approved_at = timezone.now()
        leave_req.approved_by = "Manager" # In real app, request.user
        leave_req.save()

        return Response(self.get_serializer(leave_req).data)

    @action(detail=True, methods=['patch'])
    def reject(self, request, pk=None):
        leave_req = self.get_object()
        if leave_req.status != 'Pending':
            return Response({"detail": "Only pending requests can be rejected."}, status=status.HTTP_400_BAD_REQUEST)

        leave_req.status = 'Rejected'
        leave_req.manager_comments = request.data.get('manager_comments', '')
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

class HolidayViewSet(viewsets.ModelViewSet):
    queryset = Holiday.objects.all()
    serializer_class = HolidaySerializer

from django.contrib import admin, messages
from django.db import transaction
from django.core.exceptions import PermissionDenied
from authentication.permissions import isolate_queryset
from payroll.service import LockService
from .models import DailyAttendance, PunchLog, RegularizationRequest

@admin.register(DailyAttendance)
class DailyAttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'attendance_date', 'first_check_in', 'last_check_out', 'attendance_status', 'is_locked_display')
    list_filter = ('attendance_status', 'attendance_date')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__code')
    change_list_template = "admin/attendance/dailyattendance/change_list.html"
    actions = ['delete_selected_attendance']
    list_per_page = 200

    @admin.display(description="Payroll Locked", boolean=True)
    def is_locked_display(self, obj):
        return LockService.is_attendance_locked(obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return isolate_queryset(qs, request.user)

    def has_delete_permission(self, request, obj=None):
        if not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.is_superuser:
            if obj is not None and LockService.is_attendance_locked(obj):
                return False
            return True
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        actions['delete_selected_attendance'] = (
            self.__class__.delete_selected_attendance,
            'delete_selected_attendance',
            "Delete selected attendance records (Safe & Locked Protected)"
        )
        return actions

    def delete_model(self, request, obj):
        if LockService.is_attendance_locked(obj):
            raise PermissionDenied(
                f"Attendance record for {obj.employee} on {obj.attendance_date} is locked by finalized payroll and cannot be deleted."
            )
        with transaction.atomic():
            PunchLog.objects.filter(daily_attendance=obj).delete()
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """
        Intercept Django's standard delete_selected bulk action to guarantee lock & isolation safety.
        """
        allowed_qs = isolate_queryset(queryset, request.user)
        to_delete = []
        locked_count = 0

        for att in allowed_qs:
            if LockService.is_attendance_locked(att):
                locked_count += 1
            else:
                to_delete.append(att.id)

        deleted_count = 0
        if to_delete:
            with transaction.atomic():
                PunchLog.objects.filter(daily_attendance_id__in=to_delete).delete()
                deleted_count, _ = DailyAttendance.objects.filter(id__in=to_delete).delete()

        if deleted_count > 0:
            self.message_user(
                request,
                f"Successfully deleted {deleted_count} attendance record(s).",
                messages.SUCCESS
            )
        if locked_count > 0:
            self.message_user(
                request,
                f"Notice: {locked_count} record(s) could not be deleted because payroll is locked/finalized for those periods.",
                messages.WARNING
            )
        if not to_delete and locked_count == 0:
            self.message_user(
                request,
                "No records were eligible for deletion within your authorized scope.",
                messages.ERROR
            )

    @admin.action(description="Delete selected attendance records (Safe & Locked Protected)")
    def delete_selected_attendance(self, *args, **kwargs):
        if len(args) == 2:
            request, queryset = args
        elif len(args) == 3:
            _, request, queryset = args
        else:
            request = kwargs.get('request')
            queryset = kwargs.get('queryset')
        self.delete_queryset(request, queryset)

@admin.register(PunchLog)
class PunchLogAdmin(admin.ModelAdmin):
    list_display = ('employee', 'punch_time', 'punch_type', 'source', 'daily_attendance')
    list_filter = ('punch_type', 'source', 'punch_time')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__code')
    list_per_page = 200

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return isolate_queryset(qs, request.user)

@admin.register(RegularizationRequest)
class RegularizationRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'attendance_date', 'status', 'created_at')
    list_filter = ('status', 'attendance_date')

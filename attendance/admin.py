from django.contrib import admin
from .models import DailyAttendance, PunchLog, RegularizationRequest

@admin.register(DailyAttendance)
class DailyAttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'attendance_date', 'first_check_in', 'last_check_out', 'attendance_status')
    list_filter = ('attendance_status', 'attendance_date')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__code')

@admin.register(PunchLog)
class PunchLogAdmin(admin.ModelAdmin):
    list_display = ('employee', 'punch_time', 'punch_type', 'source', 'daily_attendance')
    list_filter = ('punch_type', 'source', 'punch_time')

@admin.register(RegularizationRequest)
class RegularizationRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'attendance_date', 'status', 'created_at')
    list_filter = ('status', 'attendance_date')

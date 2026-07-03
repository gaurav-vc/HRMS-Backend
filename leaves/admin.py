from django.contrib import admin
from .models import LeaveType, LeaveBalance, LeaveRequest

@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'annual_entitlement', 'active')

@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'allocated_days', 'used_days', 'remaining_days', 'year')
    list_filter = ('year', 'leave_type')

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'start_date', 'end_date', 'total_days', 'status')
    list_filter = ('status', 'leave_type')

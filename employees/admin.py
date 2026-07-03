from django.contrib import admin
from .models import Employee

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('code', 'first_name', 'last_name', 'email', 'department', 'designation', 'status')
    search_fields = ('code', 'first_name', 'last_name', 'email')
    list_filter = ('status', 'gender', 'entity', 'branch')

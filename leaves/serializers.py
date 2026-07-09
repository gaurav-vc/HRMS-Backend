from rest_framework import serializers
from .models import LeaveType, LeaveBalance, LeaveRequest, Holiday, LeavePolicyConfiguration
from employees.models import Employee

class LeavePolicyConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeavePolicyConfiguration
        fields = '__all__'

class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = '__all__'

class LeaveBalanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    leave_type_code = serializers.CharField(source='leave_type.code', read_only=True)

    class Meta:
        model = LeaveBalance
        fields = '__all__'

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"

class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_designation = serializers.SerializerMethodField()
    employee_entity = serializers.SerializerMethodField()
    leave_type_code = serializers.CharField(source='leave_type.code', read_only=True)
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), required=False)

    class Meta:
        model = LeaveRequest
        fields = '__all__'
        read_only_fields = ('status', 'manager_comments', 'approved_by', 'approved_at', 'total_days', 'salary_deduction_days')

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"

    def get_employee_designation(self, obj):
        return obj.employee.designation.title if getattr(obj.employee, 'designation', None) else "—"

    def get_employee_entity(self, obj):
        return obj.employee.entity.name if getattr(obj.employee, 'entity', None) else "—"

    def validate(self, data):
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        employee = data.get('employee')
        
        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError("Start date must be before or equal to end date.")

        if start_date and end_date and employee:
            # Overlap check
            overlapping = LeaveRequest.objects.filter(
                employee=employee,
                status__in=['Pending', 'Approved'],
                start_date__lte=end_date,
                end_date__gte=start_date
            )
            # If updating, exclude self
            if self.instance:
                overlapping = overlapping.exclude(pk=self.instance.pk)
                
            if overlapping.exists():
                raise serializers.ValidationError("Leave request overlaps with an existing pending or approved leave.")

        return data

class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = '__all__'

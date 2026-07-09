from rest_framework import serializers
from .models import DailyAttendance, PunchLog, RegularizationRequest, FaceProfile, DynamicQRToken, ShiftDefinition, ShiftAssignment, Holiday, HolidayRuleGroup
from employees.serializers import EmployeeSerializer

class FaceProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FaceProfile
        fields = '__all__'

class DynamicQRTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DynamicQRToken
        fields = '__all__'

class PunchLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PunchLog
        fields = '__all__'

class DailyAttendanceSerializer(serializers.ModelSerializer):
    punches = PunchLogSerializer(many=True, read_only=True)
    employee_name = serializers.CharField(source='employee.first_name', read_only=True)
    employee_code = serializers.CharField(source='employee.code', read_only=True)
    
    class Meta:
        model = DailyAttendance
        fields = '__all__'

class RegularizationRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField(read_only=True)
    employee_designation = serializers.SerializerMethodField(read_only=True)
    employee_entity = serializers.SerializerMethodField(read_only=True)
    from employees.models import Employee
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), required=False)
    
    class Meta:
        model = RegularizationRequest
        fields = '__all__'
        
    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"

    def get_employee_designation(self, obj):
        return obj.employee.designation.title if getattr(obj.employee, 'designation', None) else "—"

    def get_employee_entity(self, obj):
        return obj.employee.entity.name if getattr(obj.employee, 'entity', None) else "—"

class ShiftDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShiftDefinition
        fields = '__all__'

class ShiftAssignmentSerializer(serializers.ModelSerializer):
    shift_details = ShiftDefinitionSerializer(source='shift', read_only=True)
    
    class Meta:
        model = ShiftAssignment
        fields = '__all__'

class HolidayRuleGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = HolidayRuleGroup
        fields = '__all__'

class HolidaySerializer(serializers.ModelSerializer):
    rule_groups = HolidayRuleGroupSerializer(many=True, read_only=True)
    
    class Meta:
        model = Holiday
        fields = '__all__'

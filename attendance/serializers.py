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
    
    # New computed fields for advanced CSV export
    full_name = serializers.SerializerMethodField(read_only=True)
    shift_name = serializers.SerializerMethodField(read_only=True)
    shift_start = serializers.SerializerMethodField(read_only=True)
    shift_end = serializers.SerializerMethodField(read_only=True)
    shift_hours = serializers.SerializerMethodField(read_only=True)
    early_coming = serializers.SerializerMethodField(read_only=True)
    late_coming = serializers.SerializerMethodField(read_only=True)
    status_text = serializers.SerializerMethodField(read_only=True)
    designation = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = DailyAttendance
        fields = '__all__'

    def get_full_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name or ''}".strip()

    def get_designation(self, obj):
        if hasattr(obj.employee, 'designation') and obj.employee.designation:
            return obj.employee.designation.title
        return "Employee"

    def _get_shift(self, obj):
        if not hasattr(obj, '_cached_shift'):
            request = self.context.get('request')
            if request:
                if not hasattr(request, '_shift_map'):
                    from attendance.models import ShiftAssignment
                    assignments = ShiftAssignment.objects.filter(
                        date=obj.attendance_date
                    ).select_related('shift')
                    request._shift_map = {
                        (a.employee_id, a.date): a.shift for a in assignments
                    }
                obj._cached_shift = request._shift_map.get((obj.employee_id, obj.attendance_date))
                if obj._cached_shift is None:
                    if not hasattr(request, '_default_shift'):
                        from attendance.models import ShiftDefinition
                        request._default_shift = ShiftDefinition.objects.filter(is_active=True).first()
                    obj._cached_shift = request._default_shift
            else:
                from attendance.models import ShiftAssignment, ShiftDefinition
                assignment = ShiftAssignment.objects.filter(employee_id=obj.employee_id, date=obj.attendance_date).select_related('shift').first()
                obj._cached_shift = assignment.shift if assignment else ShiftDefinition.objects.filter(is_active=True).first()
        return obj._cached_shift

    def get_shift_name(self, obj):
        shift = self._get_shift(obj)
        return shift.name if shift else "Not Assigned"

    def get_shift_start(self, obj):
        shift = self._get_shift(obj)
        return shift.start_time.strftime('%I:%M %p') if shift else "Not Assigned"

    def get_shift_end(self, obj):
        shift = self._get_shift(obj)
        return shift.end_time.strftime('%I:%M %p') if shift else "Not Assigned"

    def get_shift_hours(self, obj):
        import datetime
        shift = self._get_shift(obj)
        if shift:
            start = datetime.datetime.combine(obj.attendance_date, shift.start_time)
            end = datetime.datetime.combine(obj.attendance_date, shift.end_time)
            if end < start: end += datetime.timedelta(days=1)
            duration = (end - start).total_seconds()
            return f"{int(duration // 3600):02d}:{int((duration % 3600) // 60):02d}"
        return "00:00"

    def get_early_coming(self, obj):
        if not obj.first_check_in: return "00:00"
        shift = self._get_shift(obj)
        if not shift: return "00:00"
        import datetime
        from django.utils import timezone
        start_time = shift.start_time
        start_dt = datetime.datetime.combine(obj.attendance_date, start_time)
        in_time = obj.first_check_in
        if timezone.is_aware(in_time): start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
        if in_time < start_dt:
            diff = (start_dt - in_time).total_seconds()
            return f"{int(diff // 3600):02d}:{int((diff % 3600) // 60):02d}"
        return "00:00"

    def get_late_coming(self, obj):
        if not obj.first_check_in: return "00:00"
        shift = self._get_shift(obj)
        if not shift: return "00:00"
        import datetime
        from django.utils import timezone
        start_time = shift.start_time
        grace = shift.grace_minutes
        start_dt = datetime.datetime.combine(obj.attendance_date, start_time) + datetime.timedelta(minutes=grace)
        in_time = obj.first_check_in
        if timezone.is_aware(in_time): start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
        if in_time > start_dt:
            diff = (in_time - start_dt).total_seconds()
            return f"{int(diff // 3600):02d}:{int((diff % 3600) // 60):02d}"
        return "00:00"

    def get_status_text(self, obj):
        if obj.attendance_status == 'Absent': return 'Absent'
        status = []
        late = self.get_late_coming(obj)
        early = self.get_early_coming(obj)
        if late != "00:00" and late != "—": status.append("Late")
        elif early != "00:00" and early != "—": status.append("Early")
        else: status.append("On Time")
        if obj.overtime_hours and obj.overtime_hours > 0: status.append("OT")
        return " + ".join(status)

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

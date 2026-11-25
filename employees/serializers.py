from rest_framework import serializers
from .models import Employee, EmployeeDocument

class EmployeeDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeDocument
        fields = '__all__'


class EmployeeSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    designation_name = serializers.CharField(source='designation.title', read_only=True)
    role_name = serializers.CharField(source='dynamic_role.name', read_only=True)
    site_name = serializers.CharField(source='site.name', read_only=True)
    entity_name = serializers.CharField(source='entity.name', read_only=True)
    salary_structure_name = serializers.SerializerMethodField()
    manager_name = serializers.SerializerMethodField()
    code = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_wfh = serializers.SerializerMethodField()
    
    class Meta:
        model = Employee
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        
        from authentication.permissions import can_view_salary
        if not can_view_salary(user, instance):
            data['ctc'] = None
            data['ctc_masked'] = "xxxx"
            data['is_salary_confidential'] = True
        else:
            data['is_salary_confidential'] = False

        data['workerType'] = instance.worker_type
        data['tdsApplicable'] = instance.tds_applicable
        data['tdsSection'] = instance.tds_section
        data['tdsRate'] = float(instance.tds_rate) if instance.tds_rate is not None else 10.0
        data['tdsLowerDeductionCert'] = instance.tds_lower_deduction_cert
        data['pfApplicable'] = instance.pf_applicable
            
        return data

    def to_internal_value(self, data):
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        if 'salaryStructure' in data:
            data['salary_structure'] = data.pop('salaryStructure')
        if 'taxRegime' in data:
            data['tax_regime'] = data.pop('taxRegime')
        if 'taxSavingDeductions' in data:
            data['tax_saving_deductions'] = data.pop('taxSavingDeductions')
        if 'groupCategory' in data:
            data['group_category'] = data.pop('groupCategory')
        if 'gradeCategory' in data:
            data['grade_category'] = data.pop('gradeCategory')
        if 'workerType' in data:
            data['worker_type'] = data.pop('workerType')
        if 'tdsApplicable' in data:
            data['tds_applicable'] = data.pop('tdsApplicable')
        if 'tdsSection' in data:
            data['tds_section'] = data.pop('tdsSection')
        if 'tdsRate' in data:
            data['tds_rate'] = data.pop('tdsRate')
        if 'tdsLowerDeductionCert' in data:
            data['tds_lower_deduction_cert'] = data.pop('tdsLowerDeductionCert')
        if 'pfApplicable' in data:
            data['pf_applicable'] = data.pop('pfApplicable')

        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        from authentication.permissions import is_ceo_user
        if not is_ceo_user(user):
            # Non-CEO users cannot set, update, or clear employee CTC or tax deductions
            data.pop('ctc', None)
            data.pop('tax_saving_deductions', None)
            data.pop('salary_structure', None)

        return super().to_internal_value(data)

    def validate(self, attrs):
        email = attrs.get('email')
        phone = attrs.get('phone')
        # On creation, at least email OR phone must be present
        if not self.instance:
            if not email and not phone:
                raise serializers.ValidationError({"non_field_errors": ["Either an Email or a Phone number is required to register an employee."]})
        return attrs
        
    def get_salary_structure_name(self, obj):
        return obj.salary_structure.name if obj.salary_structure else None

    def get_manager_name(self, obj):
        if obj.manager:
            return f"{obj.manager.first_name} {obj.manager.last_name}"
        return None

    def get_is_wfh(self, obj):
        if hasattr(obj, 'dynamic_role') and obj.dynamic_role:
            perms = obj.dynamic_role.permissions or {}
            att_perms = perms.get('attendance', {})
            if isinstance(att_perms, dict) and (att_perms.get('bypass_geofence') or att_perms.get('remote_punch')):
                return True
            if perms.get('bypass_geofence') or perms.get('remote_punch'):
                return True
            scope = str(obj.dynamic_role.access_scope or '').strip().lower()
            if scope in ('corporate', 'region'):
                return True
            if getattr(obj.dynamic_role, 'can_manage_users', False):
                return True
        request = self.context.get('request')
        if request:
            if not hasattr(request, '_cached_wfh_emp_ids'):
                from organisation.models import AttendancePolicy
                request._cached_wfh_emp_ids = set(
                    AttendancePolicy.objects.filter(wfh_employees__isnull=False).values_list('wfh_employees__id', flat=True)
                )
            return obj.id in request._cached_wfh_emp_ids
        from organisation.models import AttendancePolicy
        return AttendancePolicy.objects.filter(wfh_employees=obj).exists()

from .models import EmployeeDocument, EmployeeTransfer, EmployeeExit

class EmployeeDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeDocument
        fields = '__all__'

class EmployeeTransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeTransfer
        fields = '__all__'

class EmployeeExitSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.CharField(source="employee.code", default="", read_only=True)
    department_name = serializers.CharField(source="employee.department.name", default="", read_only=True)
    designation_name = serializers.CharField(source="employee.designation.name", default="", read_only=True)

    class Meta:
        model = EmployeeExit
        fields = '__all__'

    def get_employee_name(self, obj):
        if obj.employee:
            return f"{obj.employee.first_name} {obj.employee.last_name}".strip()
        return ""

from .models import Notification, CompensationHistory


class CompensationHistorySerializer(serializers.ModelSerializer):
    salary_structure_name = serializers.CharField(
        source="salary_structure.name", default="", read_only=True
    )
    changed_by_name = serializers.SerializerMethodField()
    employee_code = serializers.CharField(
        source="employee.code", default="", read_only=True
    )
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = CompensationHistory
        fields = "__all__"

    def get_changed_by_name(self, obj):
        if obj.changed_by:
            return obj.changed_by.get_full_name() or obj.changed_by.username
        return ""

    def get_employee_name(self, obj):
        if obj.employee:
            return f"{obj.employee.first_name} {obj.employee.last_name}".strip()
        return ""


class NotificationSerializer(serializers.ModelSerializer):
    related_run_period = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = '__all__'

    def get_related_run_period(self, obj):
        if obj.related_run_id:
            try:
                from payroll.models import PayrollRun
                run = PayrollRun.objects.filter(id=obj.related_run_id).values_list('period', flat=True).first()
                return run or ''
            except Exception:
                return ''
        return ''

from .models import OfferLetter, OfferTemplate

class OfferTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfferTemplate
        fields = '__all__'

class OfferLetterSerializer(serializers.ModelSerializer):
    candidate_name = serializers.SerializerMethodField()
    candidate_email = serializers.SerializerMethodField()
    designation_name = serializers.CharField(source='employee.designation.title', read_only=True)
    department_name = serializers.CharField(source='employee.department.name', read_only=True)
    entity_name = serializers.CharField(source='employee.site.branch.entity.name', read_only=True, default='')
    joining_date = serializers.SerializerMethodField()

    class Meta:
        model = OfferLetter
        fields = '__all__'

    def get_candidate_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"
    
    def get_candidate_email(self, obj):
        return obj.employee.email

    def get_joining_date(self, obj):
        # Fallback to employee.doj if OfferLetter.joining_date is not set
        if obj.joining_date:
            return obj.joining_date
        return obj.employee.doj if hasattr(obj, 'employee') and obj.employee else None

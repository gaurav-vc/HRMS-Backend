from rest_framework import serializers
from .models import PayrollRun, Loan, Reimbursement, ComponentRule, ComplianceReport, SalaryStructure, PayrollRunComment

class ComponentRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComponentRule
        fields = '__all__'

class SalaryStructureSerializer(serializers.ModelSerializer):
    components = ComponentRuleSerializer(many=True, read_only=True)
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = SalaryStructure
        fields = '__all__'
    
    def get_employee_count(self, obj):
        try:
            return obj.employees.count()
        except Exception:
            return 0

class PayrollRunCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    
    class Meta:
        model = PayrollRunComment
        fields = ['id', 'comment', 'timestamp', 'author_name']
        
    def get_author_name(self, obj):
        if obj.author and hasattr(obj.author, 'employee_profile') and obj.author.employee_profile:
            return f"{obj.author.employee_profile.first_name} {obj.author.employee_profile.last_name}"
        return obj.author.username if obj.author else "Unknown"

class PayrollRunSerializer(serializers.ModelSerializer):
    employees = serializers.SerializerMethodField()
    gross = serializers.SerializerMethodField()
    deductions = serializers.SerializerMethodField()
    net = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    exceptions = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = '__all__'
        
    def get_employees(self, obj):
        return obj.payslip_set.count() if hasattr(obj, 'payslip_set') else 0
        
    def _can_view_confidential(self):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        emp = getattr(user, 'employee_profile', None)
        if emp and emp.dynamic_role and emp.dynamic_role.permissions and emp.dynamic_role.permissions.get('can_view_confidential_payroll'):
            return True
        return False
        
    def get_gross(self, obj):
        if not self._can_view_confidential():
            return 0
        from django.db.models import Sum
        if hasattr(obj, 'payslip_set'):
            return obj.payslip_set.aggregate(Sum('gross'))['gross__sum'] or 0
        return 0

    def get_deductions(self, obj):
        if not self._can_view_confidential():
            return 0
        from django.db.models import Sum
        if hasattr(obj, 'payslip_set'):
            return obj.payslip_set.aggregate(Sum('deductions'))['deductions__sum'] or 0
        return 0

    def get_net(self, obj):
        if not self._can_view_confidential():
            return 0
        from django.db.models import Sum
        if hasattr(obj, 'payslip_set'):
            return obj.payslip_set.aggregate(Sum('net'))['net__sum'] or 0
        return 0
        
    def get_comments(self, obj):
        # Return the latest comments to show rejection reasons
        comments = obj.comments.all().order_by('-timestamp')[:5]
        return PayrollRunCommentSerializer(comments, many=True).data

    def get_exceptions(self, obj):
        if hasattr(obj, 'payrollexception_set'):
            return [e.error_trace for e in obj.payrollexception_set.all()]
        return []

class LoanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loan
        fields = '__all__'

class ReimbursementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reimbursement
        fields = '__all__'

class ComplianceReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceReport
        fields = '__all__'

from .models import Form16Document

class Form16DocumentSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    designation_title = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Form16Document
        fields = '__all__'
        
    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"
        
    def get_employee_code(self, obj):
        return obj.employee.code
        
    def get_department_name(self, obj):
        return obj.employee.department.name if getattr(obj.employee, 'department', None) else ""
        
    def get_designation_title(self, obj):
        return obj.employee.designation.title if getattr(obj.employee, 'designation', None) else ""
        
    def get_branch_name(self, obj):
        return obj.employee.branch.name if getattr(obj.employee, 'branch', None) else ""
        
    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            if hasattr(obj.uploaded_by, 'employee_profile') and obj.uploaded_by.employee_profile:
                return f"{obj.uploaded_by.employee_profile.first_name} {obj.uploaded_by.employee_profile.last_name}"
            return obj.uploaded_by.username
        return ""

from .models import CTCImportHistory

class CTCImportHistorySerializer(serializers.ModelSerializer):
    imported_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CTCImportHistory
        fields = '__all__'
        
    def get_imported_by_name(self, obj):
        if obj.imported_by:
            if hasattr(obj.imported_by, 'employee_profile') and obj.imported_by.employee_profile:
                return f"{obj.imported_by.employee_profile.first_name} {obj.imported_by.employee_profile.last_name}"
            return obj.imported_by.username
        return ""

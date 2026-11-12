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
        if user.is_superuser:
            return True
        emp = getattr(user, 'employee_profile', None)
        if emp and emp.role in ['super_admin', 'org_admin', 'admin']:
            return True
        from organisation.models import Site
        if Site.objects.filter(contact_email=user.email).exists():
            return True
        if emp and emp.dynamic_role and emp.dynamic_role.permissions:
            perms = emp.dynamic_role.permissions
            if perms.get('can_view_confidential_payroll') in [True, 'true', 'True', 1, '1'] or perms.get('can_view_confidential') in [True, 'true', 'True', 1, '1']:
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

    def validate(self, data):
        employee = data.get('employee')
        
        # If updating an existing loan, we might not need to run these creation validations
        # or we might need to be careful. Check if this is a creation.
        if self.instance is None and employee:
            active_loans = Loan.objects.filter(employee=employee).exclude(status='Closed')
            
            if active_loans.count() >= 3:
                raise serializers.ValidationError("professional limit reached and 3 loans")
                
            if active_loans.filter(status='Pending').exists():
                raise serializers.ValidationError("You have a pending loan request that has not been approved yet. You cannot apply for another loan until it is approved.")
                
        return data

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

from .models import (
    CTCImportHistory, WalletPolicy, EmployeeWallet, WalletLedgerEntry,
    DisciplinaryInfractionCategory, EmployeeDisciplinaryMemo
)

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


class WalletPolicySerializer(serializers.ModelSerializer):
    site_name = serializers.CharField(source='site.name', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = WalletPolicy
        fields = '__all__'


class WalletLedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletLedgerEntry
        fields = '__all__'


class EmployeeWalletSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.CharField(source='employee.code', read_only=True)
    department_name = serializers.SerializerMethodField()
    designation_title = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()
    site_name = serializers.CharField(source='employee.site.name', read_only=True)
    effective_ceiling = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    recent_transactions = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeWallet
        fields = [
            'id', 'employee', 'employee_name', 'employee_code',
            'department_name', 'designation_title', 'role_name', 'site_name',
            'is_active', 'current_balance', 'custom_target_ceiling',
            'effective_ceiling', 'recent_transactions', 'updated_at'
        ]

    def get_employee_name(self, obj):
        emp = obj.employee
        name = f"{emp.first_name} {emp.last_name}".strip()
        if name:
            return name
        if emp.user:
            uname = f"{emp.user.first_name} {emp.user.last_name}".strip()
            return uname or emp.user.username
        return f"Employee #{emp.id}"

    def get_role_name(self, obj):
        emp = obj.employee
        if emp.dynamic_role and emp.dynamic_role.name:
            return emp.dynamic_role.name
        if emp.designation and emp.designation.title:
            return emp.designation.title
        if emp.role:
            return emp.role.replace('_', ' ').title()
        return "—"

    def get_designation_title(self, obj):
        emp = obj.employee
        if emp.designation and emp.designation.title:
            return emp.designation.title
        if emp.dynamic_role and emp.dynamic_role.name:
            return emp.dynamic_role.name
        return "—"

    def get_department_name(self, obj):
        emp = obj.employee
        if emp.department and emp.department.name:
            return emp.department.name
        if emp.dynamic_role and emp.dynamic_role.department and emp.dynamic_role.department.name:
            return emp.dynamic_role.department.name
        return "—"

    def get_recent_transactions(self, obj):
        txns = obj.transactions.all().order_by('-created_at')[:10]
        return WalletLedgerEntrySerializer(txns, many=True).data

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Guarantee both camelCase and snake_case properties
        ret['employeeName'] = ret.get('employee_name')
        ret['employeeCode'] = ret.get('employee_code')
        ret['roleName'] = ret.get('role_name')
        ret['designationTitle'] = ret.get('designation_title')
        ret['departmentName'] = ret.get('department_name')
        ret['siteName'] = ret.get('site_name')
        ret['isActive'] = ret.get('is_active')
        ret['currentBalance'] = ret.get('current_balance')
        ret['customTargetCeiling'] = ret.get('custom_target_ceiling')
        ret['effectiveCeiling'] = ret.get('effective_ceiling')
        return ret


class DisciplinaryInfractionCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DisciplinaryInfractionCategory
        fields = '__all__'


class EmployeeDisciplinaryMemoSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.CharField(source='employee.code', read_only=True)
    department_name = serializers.SerializerMethodField()
    designation_title = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()
    site_id = serializers.IntegerField(source='employee.site.id', read_only=True)
    site_name = serializers.CharField(source='employee.site.name', read_only=True)
    issuer_name = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    payroll_period = serializers.CharField(source='payroll_run.period', read_only=True)

    class Meta:
        model = EmployeeDisciplinaryMemo
        fields = [
            'id', 'employee', 'employee_name', 'employee_code',
            'department_name', 'designation_title', 'role_name',
            'site_id', 'site_name', 'issued_by', 'issuer_name',
            'category', 'category_name', 'is_custom_reason',
            'infraction_reason', 'description', 'amount',
            'incident_date', 'status', 'is_active',
            'payroll_run', 'payroll_period', 'payslip',
            'deducted_at', 'created_at', 'updated_at'
        ]

    def get_employee_name(self, obj):
        emp = obj.employee
        name = f"{emp.first_name} {emp.last_name}".strip()
        if name:
            return name
        if emp.user:
            uname = f"{emp.user.first_name} {emp.user.last_name}".strip()
            return uname or emp.user.username
        return f"Employee #{emp.id}"

    def get_issuer_name(self, obj):
        if not obj.issued_by:
            return "System / Admin"
        issuer = obj.issued_by
        name = f"{issuer.first_name} {issuer.last_name}".strip()
        if name:
            return name
        if issuer.user:
            uname = f"{issuer.user.first_name} {issuer.user.last_name}".strip()
            return uname or issuer.user.username
        return f"Employee #{issuer.id}"

    def get_role_name(self, obj):
        emp = obj.employee
        if emp.dynamic_role and emp.dynamic_role.name:
            return emp.dynamic_role.name
        if emp.designation and emp.designation.title:
            return emp.designation.title
        if emp.role:
            return emp.role.replace('_', ' ').title()
        return "—"

    def get_designation_title(self, obj):
        emp = obj.employee
        if emp.designation and emp.designation.title:
            return emp.designation.title
        if emp.dynamic_role and emp.dynamic_role.name:
            return emp.dynamic_role.name
        return "—"

    def get_department_name(self, obj):
        emp = obj.employee
        if emp.department and emp.department.name:
            return emp.department.name
        if emp.dynamic_role and emp.dynamic_role.department and emp.dynamic_role.department.name:
            return emp.dynamic_role.department.name
        return "—"

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Guarantee both camelCase and snake_case properties
        ret['employeeName'] = ret.get('employee_name')
        ret['employeeCode'] = ret.get('employee_code')
        ret['roleName'] = ret.get('role_name')
        ret['designationTitle'] = ret.get('designation_title')
        ret['departmentName'] = ret.get('department_name')
        ret['siteId'] = ret.get('site_id')
        ret['siteName'] = ret.get('site_name')
        ret['issuerName'] = ret.get('issuer_name')
        ret['categoryName'] = ret.get('category_name')
        ret['isCustomReason'] = ret.get('is_custom_reason')
        ret['infractionReason'] = ret.get('infraction_reason')
        ret['incidentDate'] = ret.get('incident_date')
        ret['isActive'] = ret.get('is_active')
        ret['payrollPeriod'] = ret.get('payroll_period')
        ret['deductedAt'] = ret.get('deducted_at')
        ret['createdAt'] = ret.get('created_at')
        return ret


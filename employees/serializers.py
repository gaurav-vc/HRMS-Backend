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
    
    class Meta:
        model = Employee
        fields = '__all__'
        
    def get_salary_structure_name(self, obj):
        return obj.salary_structure.name if obj.salary_structure else None

    def get_manager_name(self, obj):
        if obj.manager:
            return f"{obj.manager.first_name} {obj.manager.last_name}"
        return None

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
    class Meta:
        model = EmployeeExit
        fields = '__all__'

from .models import Notification
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'

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

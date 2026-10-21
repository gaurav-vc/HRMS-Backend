from rest_framework import serializers
from .models import Announcement, AnnouncementReceipt

class AnnouncementSerializer(serializers.ModelSerializer):
    role_names = serializers.SerializerMethodField(read_only=True)
    department_names = serializers.SerializerMethodField(read_only=True)
    target_employee_names = serializers.SerializerMethodField(read_only=True)
    author_name = serializers.SerializerMethodField(read_only=True)
    attachment_url = serializers.SerializerMethodField(read_only=True)
    is_read = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Announcement
        fields = '__all__'

    def to_internal_value(self, data):
        # Support QueryDict getlist and camelCase keys
        if hasattr(data, 'getlist'):
            raw = {}
            for k in data.keys():
                val_list = data.getlist(k)
                if k in ('target_employees', 'target_departments', 'target_roles', 'targetEmployees', 'targetDepartments', 'targetRoles'):
                    raw[k] = val_list
                else:
                    raw[k] = val_list[0] if len(val_list) == 1 else val_list
            data = raw
        else:
            data = data.copy() if hasattr(data, 'copy') else dict(data)

        if 'audienceType' in data:
            data['audience_type'] = data.pop('audienceType')
        if 'targetRoles' in data:
            data['target_roles'] = data.pop('targetRoles')
        if 'targetDepartments' in data:
            data['target_departments'] = data.pop('targetDepartments')
        if 'targetEmployees' in data:
            data['target_employees'] = data.pop('targetEmployees')
        if 'attachmentName' in data:
            data['attachment_name'] = data.pop('attachmentName')

        # Ensure ManyToMany fields are lists
        for field in ('target_roles', 'target_departments', 'target_employees'):
            if field in data and data[field] is not None:
                if not isinstance(data[field], list):
                    data[field] = [data[field]]

        return super().to_internal_value(data)

    def get_role_names(self, obj):
        if hasattr(obj, 'target_roles'):
            try:
                return [r.name for r in obj.target_roles.all()]
            except Exception:
                return []
        return []

    def get_department_names(self, obj):
        return [d.name for d in obj.target_departments.all()]

    def get_target_employee_names(self, obj):
        return [f"{e.first_name} {e.last_name} ({e.code})" for e in obj.target_employees.all()]

    def _get_employee(self, user):
        if not user or not user.is_authenticated:
            return None
        emp = getattr(user, 'employee_profile', None)
        if not emp:
            from employees.models import Employee
            if user.email:
                emp = Employee.objects.filter(email__iexact=user.email).first()
            if not emp and user.username:
                emp = Employee.objects.filter(code__iexact=user.username).first()
        return emp

    def get_author_name(self, obj):
        if obj.created_by:
            emp = self._get_employee(obj.created_by)
            if emp:
                emp_name = f"{emp.first_name} {emp.last_name}".strip()
                role_label = ""
                if emp.dynamic_role and emp.dynamic_role.name:
                    role_label = emp.dynamic_role.name
                elif emp.designation and emp.designation.name:
                    role_label = emp.designation.name
                
                if emp_name and role_label:
                    return f"{emp_name} ({role_label})"
                if emp_name:
                    return emp_name

            # Fallback to User attributes
            first = getattr(obj.created_by, 'first_name', '')
            last = getattr(obj.created_by, 'last_name', '')
            name = f"{first} {last}".strip()
            if obj.created_by.is_superuser:
                return f"{name or obj.created_by.username} (Super Admin)"
            if name:
                return name
            if obj.created_by.username:
                return obj.created_by.username
            if obj.created_by.email:
                return obj.created_by.email

        if obj.entity and obj.entity.name:
            return obj.entity.name
        return "Organization Notice"

    def get_attachment_url(self, obj):
        if obj.attachment:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.attachment.url)
            return obj.attachment.url
        return None

    def get_is_read(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            emp = self._get_employee(request.user)
            if emp:
                return AnnouncementReceipt.objects.filter(announcement=obj, employee=emp).exists()
        return False


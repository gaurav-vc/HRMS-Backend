from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import User
from employees.models import Employee
from .models import LoginAuditLog
from django.utils import timezone

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # Log successful login
        request = self.context.get('request')
        ip_address = request.META.get('REMOTE_ADDR') if request else None
        
        LoginAuditLog.objects.create(
            user=self.user,
            ip_address=ip_address,
            status='SUCCESS'
        )
        
        return data

class UserProfileSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    employee_id = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()
    dashboard_type = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'employee_id', 'first_name', 'last_name', 'permissions', 'role_name', 'dashboard_type')

    def get_employee_id(self, obj):
        return obj.employee_profile.id if hasattr(obj, 'employee_profile') else None

    def get_first_name(self, obj):
        if hasattr(obj, 'employee_profile') and obj.employee_profile:
            return obj.employee_profile.first_name
        return obj.first_name

    def get_last_name(self, obj):
        if hasattr(obj, 'employee_profile') and obj.employee_profile:
            return obj.employee_profile.last_name
        return obj.last_name

    def get_role(self, obj):
        if obj.is_superuser:
            return 'super_admin'
        
        from organisation.models import Site
        if Site.objects.filter(contact_email=obj.email).exists():
            return 'site_admin'
            
        if hasattr(obj, 'employee_profile') and obj.employee_profile:
            return obj.employee_profile.role
        return 'employee'

    def get_permissions(self, obj):
        permissions = {}
        if hasattr(obj, 'employee_profile') and obj.employee_profile and obj.employee_profile.dynamic_role:
            permissions.update(obj.employee_profile.dynamic_role.permissions)
            
        from organisation.models import Site
        sites = Site.objects.filter(contact_email=obj.email)
        if sites.exists():
            for site in sites:
                if site.modules:
                    for module in site.modules:
                        permissions[module] = {'view': True}
        return permissions

    def get_role_name(self, obj):
        from organisation.models import Site
        if Site.objects.filter(contact_email=obj.email).exists():
            return 'Site Admin'
        if hasattr(obj, 'employee_profile') and obj.employee_profile and obj.employee_profile.dynamic_role:
            return obj.employee_profile.dynamic_role.name
        return None

    def get_dashboard_type(self, obj):
        from organisation.models import Site
        if Site.objects.filter(contact_email=obj.email).exists():
            return 'manager' # Site Admins see the manager/executive dashboard
        if hasattr(obj, 'employee_profile') and obj.employee_profile and obj.employee_profile.dynamic_role:
            return obj.employee_profile.dynamic_role.dashboard_type
        return None

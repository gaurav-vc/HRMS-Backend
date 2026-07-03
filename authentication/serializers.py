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
    employee_id = serializers.IntegerField(source='employee_profile.id', read_only=True)
    first_name = serializers.CharField(source='employee_profile.first_name', read_only=True)
    last_name = serializers.CharField(source='employee_profile.last_name', read_only=True)
    permissions = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()
    dashboard_type = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'employee_id', 'first_name', 'last_name', 'permissions', 'role_name', 'dashboard_type')

    def get_role(self, obj):
        if obj.is_superuser:
            return 'super_admin'
        if hasattr(obj, 'employee_profile') and obj.employee_profile:
            return obj.employee_profile.role
        return 'employee'

    def get_permissions(self, obj):
        if hasattr(obj, 'employee_profile') and obj.employee_profile and obj.employee_profile.dynamic_role:
            return obj.employee_profile.dynamic_role.permissions
        return {}

    def get_role_name(self, obj):
        if hasattr(obj, 'employee_profile') and obj.employee_profile and obj.employee_profile.dynamic_role:
            return obj.employee_profile.dynamic_role.name
        return None

    def get_dashboard_type(self, obj):
        if hasattr(obj, 'employee_profile') and obj.employee_profile and obj.employee_profile.dynamic_role:
            return obj.employee_profile.dynamic_role.dashboard_type
        return None

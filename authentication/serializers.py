from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import User
from employees.models import Employee
from .models import LoginAuditLog
from django.utils import timezone

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # Automated LWD Deactivation Logic
        if hasattr(self.user, 'employee_profile') and hasattr(self.user.employee_profile, 'exit_process'):
            exit_process = self.user.employee_profile.exit_process
            if exit_process.status == 'Approved' and exit_process.last_working_day <= timezone.now().date():
                self.user.is_active = False
                self.user.save()
                exit_process.status = 'Deactivated'
                exit_process.save()
                from rest_framework.exceptions import AuthenticationFailed
                raise AuthenticationFailed("Account deactivated: Last working day has passed.")
        
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
    site_name = serializers.SerializerMethodField()
    org_name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'employee_id', 'first_name', 'last_name', 'permissions', 'role_name', 'dashboard_type', 'site_name', 'org_name')

    def get_employee_id(self, obj):
        return obj.employee_profile.code if hasattr(obj, 'employee_profile') and obj.employee_profile else None

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
            permissions.update(obj.employee_profile.dynamic_role.permissions or {})
            permissions['can_approve'] = obj.employee_profile.dynamic_role.can_approve
            
        from organisation.models import Site
        sites = Site.objects.filter(contact_email=obj.email)
        if sites.exists():
            for site in sites:
                if site.modules:
                    for module in site.modules:
                        if isinstance(module, dict):
                            name = module.get('name')
                            if name:
                                permissions[name] = {
                                    'view': module.get('view', True),
                                    'create': module.get('create', True),
                                    'update': module.get('update', True),
                                    'delete': module.get('delete', True),
                                }
                        else:
                            # Fallback for simple string arrays - grant full access
                            permissions[module] = {'view': True, 'create': True, 'update': True, 'delete': True}
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

    def get_site_name(self, obj):
        from organisation.models import Site
        site = Site.objects.filter(contact_email=obj.email).first()
        if site:
            return site.name
        if hasattr(obj, 'employee_profile') and obj.employee_profile and hasattr(obj.employee_profile, 'site') and obj.employee_profile.site:
            return obj.employee_profile.site.name
        return None

    def get_org_name(self, obj):
        from organisation.models import Site
        site = Site.objects.filter(contact_email=obj.email).first()
        if site and site.organization:
            return site.organization.name
        if hasattr(obj, 'employee_profile') and obj.employee_profile and hasattr(obj.employee_profile, 'site') and obj.employee_profile.site:
            if obj.employee_profile.site.organization:
                return obj.employee_profile.site.organization.name
        return None
